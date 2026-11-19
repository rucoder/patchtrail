-- SPDX-License-Identifier: Apache-2.0
ALTER TABLE patches ADD COLUMN note TEXT;
CREATE TABLE links (
  patch_id INTEGER NOT NULL REFERENCES patches(id) ON DELETE CASCADE,
  url TEXT NOT NULL,
  added_at INTEGER NOT NULL,
  PRIMARY KEY (patch_id, url)
);
CREATE INDEX mails_in_reply_to ON mails(in_reply_to);
