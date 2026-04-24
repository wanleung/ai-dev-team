import 'package:drift/drift.dart';
import 'package:drift_flutter/drift_flutter.dart';
import 'package:path_provider/path_provider.dart';
import 'package:path/path.dart' as p;

import 'schema.dart';

/// Provides the singleton instance of the app database.
AppDatabase _instance = _createDatabase();

AppDatabase _createDatabase() {
  return AppDatabase(
    driftDatabase(
      name: 'news_group_connect',
      native: const DriftNativeOptions(
        databaseDirectory: getApplicationSupportDirectory,
      ),
      web: DriftWebOptions(
        sqlite3Wasm: Uri.parse('sqlite3.wasm'),
        driftWorker: Uri.parse('drift_worker.js'),
        onResult: (result) {
          if (result.missingFeatures.isNotEmpty) {
            debugPrint(
              'Using ${result.chosenImplementation} due to unsupported browser features: ${result.missingFeatures}',
            );
          }
        },
      ),
    ),
  );
}

/// Returns the singleton database instance.
AppDatabase getDatabase() {
  return _instance;
}

/// Closes the database connection. Call this when the app is disposed.
Future<void> closeDatabase() async {
  await _instance.close();
}
