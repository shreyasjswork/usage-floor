# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2026-11-18

### Added

- Terminal menu listing every T3 Code plan with its live usage windows and saved floors.
- Per-plan, per-window floors that persist until changed.
- Background supervisor that warns agents on a plan below its floor, interrupts runs after a grace period, and
  resumes parked threads when the window resets.
- Start at sign-in on Windows, a dry-run mode and a JSON status command.
- Audit log of every warning, interrupt and resume.
