---
name: flutter
description: Flutter/Dart mobile development guidance for all project phases
version: 1.0.0
roles:
  architect: true
  engineer: true
  code_reviewer: true
  qa_engineer: true
  product_manager: false
  architect_reviewer: false
  pm_reviewer: false
tags: [flutter, dart, mobile, ios, android, widget, riverpod, drift]
source: local
---

# Flutter Skill

## For Architects
- Use feature-based folder structure: `lib/features/<name>/` with `data/`, `domain/`, `presentation/` subdirs
- Use Riverpod for state management; avoid `setState` outside leaf widgets
- Drift (SQLite) for local persistence; define all tables in `lib/database/`
- Separate repositories from UI — no direct DB/API calls in widgets
- Use `go_router` for declarative navigation

## For Engineers
- After any model or provider change, run: `flutter pub run build_runner build --delete-conflicting-outputs`
- Commit generated `.g.dart` files alongside the source that generates them
- Prefer `AsyncNotifierProvider` over `FutureProvider` for mutable async state
- Never use `BuildContext` across async gaps without checking `mounted`
- Use `flutter_localizations` from day one if any UI text is user-facing
- Environment config via `--dart-define` or `flutter_dotenv`; never hard-code secrets

## For Code Reviewers
- Flag any `BuildContext` used after `await` without a `mounted` guard
- Verify `.g.dart` files are committed alongside their source models/providers
- Reject direct `http` calls inside widgets — must go through a repository layer
- Check that all `Riverpod` providers are tested with `ProviderContainer` in unit tests
- Flag `setState` in non-leaf widgets as a design smell

## For QA Engineers
- Test on both iOS Simulator and Android Emulator in CI
- Include `flutter test --coverage` in the test plan; target ≥ 80% line coverage
- Use golden tests (`matchesGoldenFile`) for widget appearance regression
- Integration tests using `flutter_test` `IntegrationTestWidgetsFlutterBinding`
- Test offline mode: disable network and verify graceful degradation
