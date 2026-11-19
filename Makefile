# SPDX-License-Identifier: Apache-2.0
test:
	uv run pytest -q

install:
	uv tool install --force .

.PHONY: test install
