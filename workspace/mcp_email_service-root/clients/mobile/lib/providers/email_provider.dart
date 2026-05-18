import 'package:flutter/foundation.dart';
import 'package:mcp_email_mobile/models/models.dart';
import 'package:mcp_email_mobile/services/services.dart';

class EmailProvider extends ChangeNotifier {
  final ApiService _apiService;
  List<EmailMessage> _emails = [];
  EmailMessage? _selectedEmail;
  bool _isLoading = false;
  bool _hasMore = true;
  String? _error;
  int _currentPage = 0;
  static const int _pageSize = 20;

  EmailProvider({required ApiService apiService}) : _apiService = apiService;

  List<EmailMessage> get emails => _emails;
  EmailMessage? get selectedEmail => _selectedEmail;
  bool get isLoading => _isLoading;
  bool get hasMore => _hasMore;
  String? get error => _error;

  Future<void> loadEmails({
    int? accountId,
    String? search,
    bool refresh = false,
  }) async {
    if (refresh) {
      _currentPage = 0;
      _emails = [];
      _hasMore = true;
    }

    if (_isLoading || !_hasMore) return;

    _isLoading = true;
    _error = null;
    notifyListeners();

    try {
      final response = await _apiService.getEmails(
        accountId: accountId,
        limit: _pageSize,
        offset: _currentPage * _pageSize,
        search: search,
      );

      final items = (response['items'] as List)
          .map((json) => EmailMessage.fromJson(json as Map<String, dynamic>))
          .toList();

      if (items.isEmpty) {
        _hasMore = false;
      } else {
        _emails.addAll(items);
        _currentPage++;
      }

      _error = null;
    } catch (e) {
      _error = e.toString();
    } finally {
      _isLoading = false;
      notifyListeners();
    }
  }

  Future<void> loadEmailDetail(int emailId) async {
    _isLoading = true;
    _error = null;
    notifyListeners();

    try {
      final data = await _apiService.getEmail(emailId);
      _selectedEmail = EmailMessage.fromJson(data);
      _error = null;
    } catch (e) {
      _error = e.toString();
      _selectedEmail = null;
    } finally {
      _isLoading = false;
      notifyListeners();
    }
  }

  Future<void> markAsRead(int emailId, bool isRead) async {
    try {
      await _apiService.markEmailRead(emailId, isRead);
      final index = _emails.indexWhere((e) => e.id == emailId);
      if (index != -1) {
        _emails[index] = _emails[index].copyWith(isRead: isRead);
        notifyListeners();
      }
      if (_selectedEmail?.id == emailId) {
        _selectedEmail = _selectedEmail!.copyWith(isRead: isRead);
        notifyListeners();
      }
    } catch (e) {
      _error = e.toString();
      notifyListeners();
    }
  }

  Future<List<int>> downloadAttachment(int emailId, int attachmentId) async {
    final response = await _apiService.downloadAttachment(
      emailId,
      attachmentId,
    );
    return response.data!;
  }

  void clearSelectedEmail() {
    _selectedEmail = null;
    notifyListeners();
  }
}
