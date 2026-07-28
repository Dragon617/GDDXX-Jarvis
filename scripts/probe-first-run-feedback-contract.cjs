const fs = require('node:fs')
const path = require('node:path')
const ui = fs.readFileSync(path.join(__dirname, '..', 'src', 'ui', 'jarvis-react', 'src', 'main.jsx'), 'utf8')
const checks = {
  providerChangeClearsError: /const changeModelProvider = \(next\) => \{\s*setError\(""\)/.test(ui),
  voiceChangeClearsError: /const changeVoiceProvider = \(next\) => \{\s*setError\(""\)/.test(ui),
  modelEditClearsError: /setModel\(event\.target\.value\); setError\(""\)/.test(ui),
  modelKeyDisablesSpellcheck: /name="apiKey"[\s\S]{0,160}spellCheck="false"/.test(ui),
  modelKeyEditClearsError: /setApiKey\(event\.target\.value\); setError\(""\)/.test(ui),
  baseUrlEditClearsError: /setBaseURL\(event\.target\.value\); setError\(""\)/.test(ui),
  voiceKeyHasName: /name="aliyunApiKey"/.test(ui),
  voiceKeyDisablesSpellcheck: /name="aliyunApiKey"[\s\S]{0,180}spellCheck="false"/.test(ui),
  voiceKeyIsExplicitlyRequired: /name="aliyunApiKey"[\s\S]{0,260}aria-required="true"/.test(ui),
  voiceKeyEditClearsError: /setAliyunApiKey\(event\.target\.value\); setError\(""\)/.test(ui)
}
const failed = Object.entries(checks).filter(([, ok]) => !ok).map(([name]) => name)
console.log(JSON.stringify({ ok: failed.length === 0, count: Object.keys(checks).length, checks, failed }, null, 2))
if (failed.length) process.exit(1)
