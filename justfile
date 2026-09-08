set dotenv-load := true

# Run Python unit and packaging tests (no Docker required).
test-cli:
    COVERAGE_RCFILE=cli/pyproject.toml uv run --project cli --group test coverage run -m pytest cli/tests/unit cli/tests/packaging
    COVERAGE_RCFILE=cli/pyproject.toml uv run --project cli --group test coverage report

# Check Python style and types without modifying source files.
check-cli:
    uv run --project cli --group test ruff check cli
    uv run --project cli --group test ruff format --check cli
    uv run --project cli --group test ty check --project cli

# Build the Python source distribution and wheel locally; never publishes.
build-cli:
    rm -rf cli/dist
    uv run --project cli python cli/scripts/bundle_image_assets.py
    uv build --project cli

# Check, test, build and publish the CLI distributions; requires UV_PUBLISH_TOKEN.
publish-cli: check-cli test-cli build-cli
    uv publish --project cli cli/dist/*

# Regenerate the component dropdown lists in issue templates from agent-images/*
update-issue-templates:
    ./scripts/update-issue-templates.sh

# Fail if the issue templates are out of sync with agent-images/*
check-issue-templates: update-issue-templates
    git diff --exit-code .github/ISSUE_TEMPLATE

# Run all local Docker image verification checks using ephemeral resources only.
test-images:
    ./scripts/test-images.sh all

# Build every image locally.
test-images-build:
    ./scripts/test-images.sh build

# Smoke-test every built image with its documented security flags.
test-images-smoke:
    ./scripts/test-images.sh smoke

# Verify in-container egress enforcement and containment behavior.
test-images-containment:
    ./scripts/test-images.sh containment

# Verify gateway-container egress enforcement and tunnelling behavior.
test-images-gateway:
    ./scripts/test-images.sh gateway

# Run static checks for image definitions and support scripts.
test-images-static:
    ./scripts/test-images.sh static
