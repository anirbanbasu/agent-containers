# Regenerate the component dropdown lists in issue templates from agent-images/*
update-issue-templates:
    ./scripts/update-issue-templates.sh

# Fail if the issue templates are out of sync with agent-images/*
check-issue-templates: update-issue-templates
    git diff --exit-code .github/ISSUE_TEMPLATE

# Local Docker image verification. These tests use only ephemeral Docker
# resources and local test servers; they never require an agent login or key.
test-images:
    ./scripts/test-images.sh all

test-images-build:
    ./scripts/test-images.sh build

test-images-smoke:
    ./scripts/test-images.sh smoke

test-images-containment:
    ./scripts/test-images.sh containment

test-images-gateway:
    ./scripts/test-images.sh gateway

test-images-static:
    ./scripts/test-images.sh static
