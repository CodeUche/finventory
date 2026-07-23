// Single source of truth for the app version = frontend/package.json "version".
// Stamps that version into every platform's build config so web, desktop, and
// mobile stay uniform. Runs automatically before each build via the
// pre<script> hooks wired in package.json (pretauri:build, pretauri:build:cloud,
// prebuild:android). Run manually with: npm run version:sync
//
// Release-time files that live outside the repo (latest.json, the download-page
// index.html) are stamped by the desktop-release flow, not here.
import { readFileSync, writeFileSync, existsSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, resolve } from 'node:path'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const pkg = JSON.parse(readFileSync(resolve(root, 'package.json'), 'utf8'))
const version = pkg.version
if (!/^\d+\.\d+\.\d+$/.test(version)) {
  console.error(`[sync-version] package.json version "${version}" is not x.y.z`)
  process.exit(1)
}

const touched = []

// Desktop — src-tauri/tauri.conf.json (tauri.cloud.conf.json inherits it).
// Regex-replace the top-level "version" value only, to keep the diff minimal.
const tauri = resolve(root, 'src-tauri/tauri.conf.json')
{
  const before = readFileSync(tauri, 'utf8')
  const after = before.replace(/("version"\s*:\s*")\d+\.\d+\.\d+(")/, `$1${version}$2`)
  if (after !== before) { writeFileSync(tauri, after); touched.push('src-tauri/tauri.conf.json') }
}

// Desktop — src-tauri/Cargo.toml [package] version (the first `version = "x.y.z"`
// in the file, which sits under [package] before any [dependencies]). Not
// user-facing, but kept in lockstep so nothing drifts.
const cargo = resolve(root, 'src-tauri/Cargo.toml')
if (existsSync(cargo)) {
  const before = readFileSync(cargo, 'utf8')
  const after = before.replace(/^(version\s*=\s*")\d+\.\d+\.\d+(")/m, `$1${version}$2`)
  if (after !== before) { writeFileSync(cargo, after); touched.push('src-tauri/Cargo.toml') }
}

// Mobile — android/app/build.gradle versionName (versionCode left manual: Play
// requires a monotonic integer, bumped deliberately at each mobile release).
const gradle = resolve(root, 'android/app/build.gradle')
if (existsSync(gradle)) {
  const before = readFileSync(gradle, 'utf8')
  const after = before.replace(/(versionName\s+")[^"]*(")/, `$1${version}$2`)
  if (after !== before) { writeFileSync(gradle, after); touched.push('android/app/build.gradle') }
}

console.log(`[sync-version] version ${version} -> ${touched.length ? touched.join(', ') : 'all files already in sync'}`)
