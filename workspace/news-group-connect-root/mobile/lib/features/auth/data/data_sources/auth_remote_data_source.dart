import 'package:dio/dio.dart';
import '../models/auth_models.dart';

class AuthRemoteDataSource {
  final Dio _dio;

  AuthRemoteDataSource({required Dio dio}) : _dio = dio;

  Future<TokenResponse> login({
    required String email,
    required String password,
  }) async {
    final response = await _dio.post<Map<String, dynamic>>(
      '/api/v1/auth/login',
      data: LoginRequest(email: email, password: password).toJson(),
    );
    return TokenResponse.fromJson(response.data!);
  }

  Future<TokenResponse> register({
    required String email,
    required String username,
    required String password,
    required String fullName,
  }) async {
    final response = await _dio.post<Map<String, dynamic>>(
      '/api/v1/auth/register',
      data: RegisterRequest(
        email: email,
        username: username,
        password: password,
        fullName: fullName,
      ).toJson(),
    );
    return TokenResponse.fromJson(response.data!);
  }

  Future<TokenResponse> refresh({required String refreshToken}) async {
    final response = await _dio.post<Map<String, dynamic>>(
      '/api/v1/auth/refresh',
      data: RefreshRequest(refreshToken: refreshToken).toJson(),
    );
    return TokenResponse.fromJson(response.data!);
  }
}
