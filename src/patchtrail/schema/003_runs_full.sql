-- SPDX-License-Identifier: Apache-2.0
ALTER TABLE runs ADD COLUMN full INTEGER NOT NULL DEFAULT 1;
CREATE INDEX run_log_run ON run_log(run_id);
