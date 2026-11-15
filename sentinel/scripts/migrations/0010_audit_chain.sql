ALTER TABLE audit ADD COLUMN row_sha TEXT;
ALTER TABLE audit ADD COLUMN chain_sha TEXT;
INSERT OR IGNORE INTO meta(key, value) VALUES ('registry_id', lower(hex(randomblob(16))));
