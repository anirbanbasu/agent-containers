# Regenerate the component dropdown lists in issue templates from agent-images/*
update-issue-templates:
    ./scripts/update-issue-templates.sh

# Fail if the issue templates are out of sync with agent-images/*
check-issue-templates: update-issue-templates
    git diff --exit-code .github/ISSUE_TEMPLATE
