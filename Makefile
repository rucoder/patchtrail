# SPDX-License-Identifier: Apache-2.0
test:
	uv run pytest -q

web:
	cd web && npm ci && npm run build

install: web
	uv tool install --force .

test-web:
	cd web && npm ci && npm test

.PHONY: test web install test-web
