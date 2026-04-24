class AppConstants {
  AppConstants._();

  static const String apiBaseUrl = String.fromEnvironment(
    'API_BASE_URL',
    defaultValue: 'http://localhost:8000/api',
  );

  static const Duration connectTimeout = Duration(seconds: 10);
  static const Duration receiveTimeout = Duration(seconds: 30);

  static const int defaultEmailLimit = 20;
  static const int defaultEmailOffset = 0;

  static const String prefSelectedAccountId = 'selected_account_id';
}

class AppTheme {
  AppTheme._();

  static const String primaryColorHex = '#1976D2';
  static const String accentColorHex = '#FF5722';
  static const String unreadIndicatorColor = '#1976D2';
  static const String readIndicatorColor = '#B0BEC5';
}
