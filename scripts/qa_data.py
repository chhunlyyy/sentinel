#!/usr/bin/env python3
import argparse
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path

import yaml

CONFIG_NAME = "sentinel.config.yaml"
DEFAULT_SUFFIXES = ["_qa", "_fresh"]


def find_config(start):
    current = Path(start).resolve()
    for folder in [current, *current.parents]:
        if (folder / CONFIG_NAME).exists():
            return folder / CONFIG_NAME
    sys.exit(f"{CONFIG_NAME} not found")


def read_env(path):
    values = {}
    for line in Path(path).read_text().splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip().strip("'\"")
    return values


class MysqlData:
    def __init__(self, config_path, config, dry_run):
        self.dry_run = dry_run
        self.workspace = config_path.parent
        qa = config.get("qa") or {}
        self.spec = qa.get("db_clone")
        if self.spec in (None, "none"):
            sys.exit("qa.db_clone is none; nothing to do")
        state_dir = (config.get("state") or {}).get("dir", ".sentinel")
        self.storage_root = self.workspace / state_dir / "cache" / "qa" / "storage"
        self.ports = qa.get("ports") or []
        self.suffixes = self.spec.get("throwaway_suffixes") or DEFAULT_SUFFIXES
        self.load_connection()

    def load_connection(self):
        conn = self.spec["connection"]
        env = read_env(self.workspace / conn["env_file"])
        url = env.get(conn.get("url_var", ""), "")
        self.params = ""
        if url:
            match = re.match(r"^jdbc:mysql://([^/]+)/[^?]*(\?.*)?$", url)
            if not match:
                sys.exit(f"cannot parse {conn['url_var']}")
            host_port, self.params = match.group(1), match.group(2) or ""
        else:
            host = env.get(conn.get("host_var", ""), "127.0.0.1")
            port = env.get(conn.get("port_var", ""), "3306")
            host_port = f"{host}:{port}"
        self.host_port = host_port
        host, _, port = host_port.partition(":")
        self.host = "127.0.0.1" if host == "localhost" else host
        self.port = port or "3306"
        self.user = env.get(conn.get("user_var", ""), "")
        self.password = env.get(conn.get("password_var", ""), "")
        if not self.dry_run and not self.user:
            sys.exit("database user not found in env file")

    def guard(self, name):
        if not any(name.endswith(suffix) for suffix in self.suffixes):
            sys.exit(f"refusing to touch non-throwaway schema '{name}' (allowed suffixes: {', '.join(self.suffixes)})")
        sources = {d["source"] for d in self.spec["databases"]}
        if name in sources:
            sys.exit(f"refusing: '{name}' is also a source schema")

    def base(self, tool):
        return [tool, f"-h{self.host}", f"-P{self.port}", f"-u{self.user or 'USER'}"]

    def sql(self, statement):
        command = self.base("mysql") + ["-N", "-e", statement]
        if self.dry_run:
            print("DRY-RUN", shlex.join(command))
            return ""
        env = {**os.environ, "MYSQL_PWD": self.password}
        result = subprocess.run(command, capture_output=True, text=True, env=env)
        if result.returncode != 0:
            sys.exit(result.stderr.strip())
        return result.stdout

    def create_empty(self, target):
        self.guard(target)
        self.sql(f"DROP DATABASE IF EXISTS `{target}`; CREATE DATABASE `{target}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;")

    def clone(self, source, target):
        self.guard(target)
        print(f"cloning {source} -> {target}")
        self.create_empty(target)
        dump = self.base("mysqldump") + ["--single-transaction", "--routines", "--triggers", "--no-tablespaces", "--set-gtid-purged=OFF", source]
        load = self.base("mysql") + [target]
        if self.dry_run:
            print("DRY-RUN", shlex.join(dump), "|", shlex.join(load))
            return
        env = {**os.environ, "MYSQL_PWD": self.password}
        producer = subprocess.Popen(dump, stdout=subprocess.PIPE, env=env)
        consumer = subprocess.run(load, stdin=producer.stdout, env=env)
        producer.stdout.close()
        if producer.wait() != 0 or consumer.returncode != 0:
            sys.exit(f"clone of {source} failed")

    def exists(self, name):
        if self.dry_run:
            return False
        return bool(self.sql(f"SHOW DATABASES LIKE '{name}'").strip())

    def prepare(self, refresh_all):
        for database in self.spec["databases"]:
            mode = database.get("refresh", "always")
            if mode == "if_missing" and not refresh_all and self.exists(database["target"]):
                print(f"reusing existing {database['target']} (pass --refresh-all to re-clone)")
                continue
            self.clone(database["source"], database["target"])
        for name in self.spec.get("storage_dirs") or []:
            directory = self.storage_root / name
            if self.dry_run:
                print("DRY-RUN mkdir", directory)
            else:
                directory.mkdir(parents=True, exist_ok=True)
        print("ready: " + ", ".join(d["target"] for d in self.spec["databases"]))

    def fresh(self):
        fresh = self.spec.get("fresh")
        if not fresh:
            sys.exit("qa.db_clone.fresh is not configured")
        self.create_empty(fresh["target"])
        print(f"ready: empty {fresh['target']}")

    def drop(self, targets):
        for target in targets:
            self.guard(target)
            self.sql(f"DROP DATABASE IF EXISTS `{target}`;")
            print(f"dropped {target}")

    def drop_fresh(self):
        fresh = self.spec.get("fresh")
        if fresh:
            self.drop([fresh["target"]])

    def drop_all(self):
        self.drop([d["target"] for d in self.spec["databases"]] + ([self.spec["fresh"]["target"]] if self.spec.get("fresh") else []))

    def boot_args(self, mode):
        targets = {d["source"]: d["target"] for d in self.spec["databases"]}
        fresh = self.spec.get("fresh")
        if mode == "fresh":
            if not fresh:
                sys.exit("qa.db_clone.fresh is not configured")
            targets[fresh.get("replaces", self.spec["databases"][0]["source"])] = fresh["target"]
        elif mode != "qa":
            sys.exit("usage: boot-args <qa|fresh>")
        port = str(self.ports[0]) if self.ports else ""
        out = []
        for template in self.spec.get("boot_args") or []:
            text = template.replace("{port}", port)
            text = re.sub(r"\{jdbc:([^}]+)\}", lambda m: f"jdbc:mysql://{self.host_port}/{targets.get(m.group(1), m.group(1))}{self.params}", text)
            text = re.sub(r"\{storage:([^}]+)\}", lambda m: str(self.storage_root / m.group(1)), text)
            out.append(text)
        print(" ".join(out))


def main():
    parser = argparse.ArgumentParser(prog="qa-data")
    parser.add_argument("--config")
    parser.add_argument("--dry-run", action="store_true", help="print the commands without running them")
    sub = parser.add_subparsers(dest="cmd", required=True)
    prepare = sub.add_parser("prepare")
    prepare.add_argument("--refresh-all", action="store_true")
    sub.add_parser("fresh")
    sub.add_parser("drop-fresh")
    sub.add_parser("drop-all")
    boot = sub.add_parser("boot-args")
    boot.add_argument("mode", choices=["qa", "fresh"])
    args = parser.parse_args()

    config_path = Path(args.config).resolve() if args.config else find_config(".")
    config = yaml.safe_load(config_path.read_text())
    data = MysqlData(config_path, config, args.dry_run)
    if args.cmd == "prepare":
        data.prepare(args.refresh_all)
    elif args.cmd == "fresh":
        data.fresh()
    elif args.cmd == "drop-fresh":
        data.drop_fresh()
    elif args.cmd == "drop-all":
        data.drop_all()
    else:
        data.boot_args(args.mode)


if __name__ == "__main__":
    main()
