// index.js — Azure DevOps task adapter.
//
// This file is intentionally thin: it reads AzDO pipeline inputs,
// shells out to the platform-agnostic Python engine (engine/sql_syntax_check.py),
// and translates the result into AzDO build output (task result,
// logging issues so they surface as build warnings/errors, and
// exposing the JSON report as a build artifact-ready variable).
//
// Porting to another platform means writing a new file like this one
// against that platform's SDK — the engine itself never changes.

const tl = require('azure-pipelines-task-lib/task');
const path = require('path');
const fs = require('fs');

async function run() {
  try {
    const sqlPath = tl.getInput('sqlPath', true);
    const dialectConfigPath = tl.getInput('dialectConfigPath', false);
    const defaultDialect = tl.getInput('defaultDialect', true);
    const failOnError = tl.getBoolInput('failOnError', false);

    const engineScript = path.join(__dirname, 'engine', 'sql_syntax_check.py');
    const jsonOutPath = path.join(tl.getVariable('Agent.TempDirectory') || '.', 'sql-syntax-report.json');

    // Prefer python3, fall back to python (Windows agents commonly only have 'python')
    let pythonExe = tl.which('python3', false) || tl.which('python', false);
    if (!pythonExe) {
      tl.setResult(tl.TaskResult.Failed, 'Neither python3 nor python was found on this agent. Ensure Python 3.8+ is installed.');
      return;
    }

    const args = [
      engineScript,
      '--path', sqlPath,
      '--root', sqlPath,
      '--default-dialect', defaultDialect,
      '--json-out', jsonOutPath,
    ];
    if (dialectConfigPath) {
      args.push('--dialect-config', dialectConfigPath);
    }

    const runner = tl.tool(pythonExe).arg(args);
    const exitCode = await runner.exec({ ignoreReturnCode: true, failOnStdErr: false });

    // Surface each file's violations as AzDO logging issues so they
    // show up inline in the build summary, not just buried in logs.
    if (fs.existsSync(jsonOutPath)) {
      tl.setVariable('SqlSyntaxCheck.ReportPath', jsonOutPath);
      const report = JSON.parse(fs.readFileSync(jsonOutPath, 'utf8'));
      for (const file of report.results) {
        for (const v of file.violations) {
          tl.command('task.logissue', {
            type: 'error',
            sourcepath: file.path,
            linenumber: String(v.line),
            columnnumber: String(v.col),
          }, `[${file.dialect}] ${v.description}`);
        }
      }
      tl.setVariable('SqlSyntaxCheck.Passed', String(report.summary.passed));
      tl.setVariable('SqlSyntaxCheck.Failed', String(report.summary.failed));
    }

    if (exitCode !== 0) {
      const msg = `SQL syntax check found errors. See logged issues above for file/line details.`;
      if (failOnError) {
        tl.setResult(tl.TaskResult.Failed, msg);
      } else {
        tl.setResult(tl.TaskResult.SucceededWithIssues, msg);
      }
    } else {
      tl.setResult(tl.TaskResult.Succeeded, 'All SQL files passed syntax check.');
    }
  } catch (err) {
    tl.setResult(tl.TaskResult.Failed, `Unhandled error: ${err.message}`);
  }
}

run();
