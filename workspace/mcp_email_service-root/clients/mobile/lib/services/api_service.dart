import 'dart:typed_data';

import 'package:dio/dio.dart';
import 'package:mcp_email_mobile/utils/constants.dart';

class ApiService {
  final Dio dio;

  ApiService({Dio? dioClient})
    : dio =
          dioClient ??
          Dio(
            BaseOptions(
              baseUrl: AppConstants.apiBaseUrl,
              connectTimeout: AppConstants.connectTimeout,
              receiveTimeout: AppConstants.receiveTimeout,
              headers: {'Content-Type': 'application/json'},
            ),
          ) {
    dio.interceptors.add(
      InterceptorsWrapper(
        onError: (error, handler) {
          if (error.response?.statusCode == 401) {
            throw UnauthorizedException('Authentication required');
          }
          return handler.next(error);
        },
      ),
    );
  }

  Future<List<dynamic>> getAccounts() async {
    final response = await dio.get('/accounts');
    return response.data as List<dynamic>;
  }

  Future<Map<String, dynamic>> createAccount({
    required String emailAddress,
    required String imapHost,
    required int imapPort,
    required String username,
    required String password,
  }) async {
    final response = await dio.post(
      '/accounts',
      data: {
        'email_address': emailAddress,
        'imap_host': imapHost,
        'imap_port': imapPort,
        'username': username,
        'password': password,
      },
    );
    return response.data as Map<String, dynamic>;
  }

  Future<Map<String, dynamic>> deleteAccount(int accountId) async {
    final response = await dio.delete('/accounts/$accountId');
    return response.data as Map<String, dynamic>;
  }

  Future<Map<String, dynamic>> syncAccount(
    int accountId, {
    List<String>? folders,
  }) async {
    final body = folders != null ? {'folders': folders} : null;
    final response = await dio.post('/accounts/$accountId/sync', data: body);
    return response.data as Map<String, dynamic>;
  }

  Future<Map<String, dynamic>> getEmails({
    int? accountId,
    int limit = AppConstants.defaultEmailLimit,
    int offset = AppConstants.defaultEmailOffset,
    String? search,
  }) async {
    final queryParameters = <String, dynamic>{'limit': limit, 'offset': offset};
    if (accountId != null) queryParameters['account_id'] = accountId;
    if (search != null && search.isNotEmpty) queryParameters['search'] = search;

    final response = await dio.get('/emails', queryParameters: queryParameters);
    return response.data as Map<String, dynamic>;
  }

  Future<Map<String, dynamic>> getEmail(int emailId) async {
    final response = await dio.get('/emails/$emailId');
    return response.data as Map<String, dynamic>;
  }

  Future<Map<String, dynamic>> markEmailRead(int emailId, bool isRead) async {
    final response = await dio.patch(
      '/emails/$emailId/read',
      data: {'is_read': isRead},
    );
    return response.data as Map<String, dynamic>;
  }

  Future<Response<Uint8List>> downloadAttachment(
    int emailId,
    int attachmentId,
  ) async {
    return dio.get<Uint8List>(
      '/emails/$emailId/attachments/$attachmentId/download',
      options: Options(responseType: ResponseType.bytes),
    );
  }
}

class UnauthorizedException implements Exception {
  final String message;
  UnauthorizedException(this.message);

  @override
  String toString() => 'UnauthorizedException: $message';
}
