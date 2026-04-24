import 'package:dartz/dartz.dart';
import '../models/auth_models.dart';

abstract class AuthRepository {
  Future<Either<String, TokenResponse>> login({
    required String email,
    required String password,
  });

  Future<Either<String, TokenResponse>> register({
    required String email,
    required String username,
    required String password,
    required String fullName,
  });

  Future<Either<String, TokenResponse>> refresh({required String refreshToken});

  Future<Either<String, void>> logout();

  Future<bool> isAuthenticated();

  Future<String?> getAccessToken();
}
