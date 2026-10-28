---
argument-hint: <jira_issue_id> <max_words>
arguments:
- jira_issue_id
- max_words
description: Drafts a short work-done comment from minimal git context and posts it
  to a Jira issue only after explicit confirmation.
---

# Jira Work-Done Comment

You are posting a single work-done comment to `$jira_issue_id`. You never change issue status, fields, assignee, links, or sub-tasks — the only side effect you perform is adding one comment.

## Task

### 1. Gather Context
- Run only `git log main..HEAD --oneline` and `git diff main..HEAD --stat` on the current branch.
- Do not read full file contents, full diffs, or other requirements/prompt files — this stays minimal-context by design.
- If both commands return empty output, ask the user for a free-text summary of the work, and use it as the sole source for drafting, instead of aborting.

### 2. Draft the Comment
- Write one short lead line, followed by a bullet list of the key changes.
- Keep the total word count (lead line + bullets) at or under `$max_words` (default 250) words.

### 3. Confirm
- Show the drafted comment to the user and ask explicit Yes/No: "Post this comment to `$jira_issue_id`? (Yes/No)"
- If the user answers **No**, let them edit or redirect the draft, then show the revised draft and ask Yes/No again before posting anything.

### 4. Post
- Only after the user answers **Yes**, post the confirmed draft to `$jira_issue_id` via the Jira MCP comment tool.
- Confirm completion to the user: "Comment posted to `$jira_issue_id`."