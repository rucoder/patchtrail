test:
	uv run pytest -q

install:
	uv tool install --force .

.PHONY: test install
