import 'package:flutter/foundation.dart';
import 'package:mcp_email_mobile/models/models.dart';
import 'package:mcp_email_mobile/services/services.dart';

class AccountProvider extends ChangeNotifier {
  final ApiService _apiService;
  List<EmailAccount> _accounts = [];
  bool _isLoading = false;
  String? _error;

  AccountProvider({required ApiService apiService}) : _apiService = apiService;

  List<EmailAccount> get accounts => _accounts;
  bool get isLoading => _isLoading;
  String? get error => _error;

  Future<void> loadAccounts() async {
    _isLoading = true;
    _error = null;
    notifyListeners();

    try {
      final data = await _apiService.getAccounts();
      _accounts = data
          .map((json) => EmailAccount.fromJson(json as Map<String, dynamic>))
          .toList();
      _error = null;
    } catch (e) {
      _error = e.toString();
      _accounts = [];
    } finally {
      _isLoading = false;
      notifyListeners();
    }
  }

  Future<void> addAccount({
    required String emailAddress,
    required String imapHost,
    required int imapPort,
    required String username,
    required String password,
  }) async {
    _isLoading = true;
    _error = null;
    notifyListeners();

    try {
      await _apiService.createAccount(
        emailAddress: emailAddress,
        imapHost: imapHost,
        imapPort: imapPort,
        username: username,
        password: password,
      );
      await loadAccounts();
    } catch (e) {
      _error = e.toString();
    } finally {
      _isLoading = false;
      notifyListeners();
    }
  }

  Future<void> removeAccount(int accountId) async {
    _isLoading = true;
    _error = null;
    notifyListeners();

    try {
      await _apiService.deleteAccount(accountId);
      _accounts.removeWhere((a) => a.id == accountId);
    } catch (e) {
      _error = e.toString();
    } finally {
      _isLoading = false;
      notifyListeners();
    }
  }

  Future<Map<String, dynamic>> triggerSync(
    int accountId, {
    List<String>? folders,
  }) async {
    return _apiService.syncAccount(accountId, folders: folders);
  }
}
