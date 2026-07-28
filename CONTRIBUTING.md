# Contributing to GDDXX-Jarvis

Thanks for helping improve GDDXX-Jarvis. Keep changes focused, explain the user-visible reason, and include verification proportional to the risk.

## Development setup

Use Windows 10 or Windows 11 x64 with Node.js 20 or 22 LTS and Git.

```powershell
git clone https://github.com/shitoudaidi/GDDXX-Jarvis.git
cd GDDXX-Jarvis
npm.cmd ci
npm.cmd run doctor:install
npm.cmd run start:desktop
```

Do not commit `config.json`, API keys, runtime data, generated installers, local models, or logs.

## Before a pull request

1. Run `npm.cmd run check`.
2. Run the probes relevant to the changed behavior.
3. Describe the problem, the solution, and the commands used to verify it.
4. Add or update a regression probe when fixing a reproducible defect.
5. Preserve the GDDXX-Jarvis identity and all applicable third-party notices.

By contributing, you agree that your contribution is provided under the repository's MIT license and that you have the right to submit it.
