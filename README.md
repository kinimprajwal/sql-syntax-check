# SQL Syntax Check

An open-source, dialect-aware SQL syntax checker, built so the same core
engine can be "mounted" on any platform. This repo currently ships an
Azure DevOps extension; the engine itself has no Azure DevOps dependency,
so a GitHub Action, pre-commit hook, or VS Code task can be added later by
writing a new thin adapter (see `azure-devops-extension/task/index.js`
for what that adapter looks like). MIT licensed — see `LICENSE`.

## Layout

```
engine/                          <- platform-agnostic core (tested standalone)
  sql_syntax_check.py
  requirements.txt
  dialects.example.json
azure-devops-extension/          <- the AzDO "mount"
  vss-extension.json             <- extension manifest (for tfx-cli)
  task/
    task.json                    <- pipeline task definition (inputs, etc.)
    index.js                     <- thin adapter: AzDO inputs -> engine -> AzDO output
    package.json
    engine/                      <- copy of engine/, bundled so the extension is self-contained
test-sql/                        <- sample good/bad files used to validate the engine
```

## 0. Block bad SQL before it's even committed (any git host — not just Azure DevOps)

This is the closest real equivalent to "don't let this file get saved with a syntax
error" — it runs locally via a git pre-commit hook, using the
[pre-commit](https://pre-commit.com) framework, so it works identically whether
your repo lives in Azure DevOps, GitHub, GitLab, or anywhere else. (True
as-you-type-in-the-editor checking would require a separate VS Code/LSP extension —
this is the commit-time equivalent, and doesn't depend on any particular editor.)

**Verified working**: attempting to commit a `.sql` file with a real syntax error
(`WHERE WHERE ...`) is rejected outright — the commit never happens — while a fixed
version commits normally.

In the repo where you want this enforced, add a `.pre-commit-config.yaml`:

```yaml
repos:
  - repo: https://github.com/YOUR_GITHUB_USERNAME/sql-syntax-check   # once pushed
    rev: v0.1.0                                                       # tag a release
    hooks:
      - id: sql-syntax-check
        args: ["--default-dialect", "tsql", "--dialect-config", "dialects.json"]
```

(While developing locally before it's pushed anywhere, point `repo:` at the local
folder path and `rev:` at a commit hash in that folder instead of a GitHub URL/tag.)

Then:
```bash
pip install pre-commit
pre-commit install        # wires it into .git/hooks/pre-commit for this repo
```

From then on, `git commit` runs the checker on whatever `.sql` files are staged and
aborts the commit if any fail to parse — no CI round-trip needed, feedback is
immediate and local. The Azure DevOps task below is still worth keeping as a
server-side safety net for anyone who commits with `--no-verify` or hasn't installed
the hook locally.

## 1. Engine — already tested standalone

```bash
pip install -r engine/requirements.txt
python engine/sql_syntax_check.py \
  --path ./your-sql-folder \
  --dialect-config engine/dialects.example.json \
  --default-dialect ansi
```

- Exit code `0` = all files parsed cleanly, `1` = at least one syntax error, `2` = tool/config error.
- `--dialect-config` maps glob patterns to dialects (supports `**` for any depth). Example:

```json
[
  { "pattern": "sqlserver/**/*.sql", "dialect": "tsql" },
  { "pattern": "snowflake/**/*.sql", "dialect": "snowflake" }
]
```

- Only **syntax-level** violations (sqlfluff rule code `PRS`) fail the check — style/formatting
  rules are deliberately excluded so this doesn't turn into a formatting gate. That can be added
  later as an opt-in `--include-style` flag if useful.
- Verified against sample files in `test-sql/`: catches a malformed `WHERE WHERE` clause in T-SQL
  and a bare `SELECT FROM WHERE;` in Snowflake SQL, while passing valid files in both dialects.

## 2. Package the Azure DevOps extension

Requires Node.js and the TFS cross-platform CLI:

```bash
npm install -g tfx-cli
cd azure-devops-extension/task
npm install          # pulls in azure-pipelines-task-lib
cd ..
```

Before packaging:
1. Add a 128x128 `images/icon.png` in `azure-devops-extension/`.
2. Replace `publisher` in `vss-extension.json` with your personal Marketplace
   publisher ID (create one free at https://marketplace.visualstudio.com/manage
   — any individual can register one, no company affiliation needed).
3. Replace the `repository.uri` placeholder once you've pushed this to GitHub —
   the Marketplace listing links back to it, which matters for an open-source
   project (lets people file issues, see the source, contribute).

```bash
tfx extension create --manifest-globs vss-extension.json
```

This produces a `.vsix` file.

## 3. Publish

**While you're still testing it**, share it privately first rather than going
straight to the public Marketplace:

```bash
tfx extension publish --manifest-globs vss-extension.json --share-with YOUR_ORG_NAME
```

**Once it's ready for other people to use it**, flip `"public": true` in
`vss-extension.json` and publish normally — it'll then be listed on the public
Marketplace under your publisher name, installable by anyone:

```bash
tfx extension publish --manifest-globs vss-extension.json
```

Marketplace review for public extensions is automated and usually fast, but can
flag things like an unclear description or missing icon — worth having those
solid before the first public publish attempt.

## 4. Use it in a pipeline

Once installed, any YAML pipeline in the org can add:

```yaml
- task: SqlSyntaxCheck@0
  inputs:
    sqlPath: '$(Build.SourcesDirectory)/sql'
    dialectConfigPath: '$(Build.SourcesDirectory)/sql/dialects.json'
    defaultDialect: 'ansi'
    failOnError: true
```

Errors are logged as inline build issues (file, line, column) via `task.logissue`, and the
task fails (or succeeds-with-issues, if `failOnError` is false) based on the result.

## Known limitations / next steps

- Requires Python 3.8+ and `sqlfluff` available on the build agent (or install as a prior
  pipeline step: `- script: pip install sqlfluff`).
- Only `tsql`, `snowflake`, and `ansi` are wired into the task's dropdown right now —
  more of sqlfluff's dialects can be added trivially since the engine already accepts any
  dialect name sqlfluff supports.
- Style/formatting rules are intentionally not enforced yet — this is scoped to "will it fail
  to run," not "is it formatted the way we like."
- No inline PR comments yet (build validation only) — that would be a second iteration using
  the Azure DevOps REST API's Pull Request Thread endpoint, once the task itself is proven out.
- **Known gap: Snowflake stored procedure bodies (`$$ ... $$`) are not actually checked.**
  sqlfluff's Snowflake dialect parses the outer `CREATE PROCEDURE ...` shell but treats the
  `$$`-delimited body as an opaque string literal — it never parses the SQL inside it. Verified
  with `test-sql/snowflake/sp_refresh_customer_summary_bad.sql`, which has a `WHERE WHERE`
  typo and a mismatched `END` inside the body and still comes back as passing. T-SQL stored
  procedures don't have this problem (their bodies are parsed normally). Until sqlfluff adds
  real Snowflake Scripting support, this tool can't be fully trusted for procedure bodies on
  Snowflake — worth calling out to anyone using it, not just quietly living with it.
