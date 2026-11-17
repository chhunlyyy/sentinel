ALTER TABLE cycles ADD COLUMN red_method TEXT NOT NULL DEFAULT 'test_file';
ALTER TABLE cycles ADD COLUMN approved_scripts TEXT;
ALTER TABLE evidence ADD COLUMN method TEXT;
ALTER TABLE evidence ADD COLUMN exception TEXT;
ALTER TABLE evidence ADD COLUMN scripts TEXT;
ALTER TABLE evidence ADD COLUMN scenarios TEXT;
ALTER TABLE evidence ADD COLUMN runs TEXT;
ALTER TABLE cycles ADD COLUMN approved_runner TEXT;
