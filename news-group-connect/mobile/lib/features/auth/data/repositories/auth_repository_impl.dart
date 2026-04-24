import 'package:dartz/dartz.dart';
import 'package:dio/dio.dart';
import '../../data/data_sources/auth_local_data_source.dart';
import '../../data/data_sources/auth_remote_data_source.dart';
import '../../data/models/auth_models.dart';
import '../repositories/auth_repository.dart';

class AuthRepositoryImpl implements AuthRepository {
  final AuthRemoteDataSource _remoteDataSource;
  final AuthLocalDataSource _localDataSource;

  AuthRepositoryImpl({
    required AuthRemoteDataSource remoteDataSource,
    required AuthLocalDataSource localDataSource,
  }) : _remoteDataSource = remoteDataSource,
       _localDataSource = localDataSource;

  @override
  Future<Either<String, TokenResponse>> login({
    required String email,
    required String password,
  }) async {
    try {
      final response = await _remoteDataSource.login(
        email: email,
        password: password,
      );
      await _localDataSource.saveTokens(
        accessToken: response.accessToken,
        refreshToken: response.refreshToken,
      );
      return Right(response);
    } on DioException catch (e) {
      return Left(e.response?.data['detail'] ?? e.message ?? 'Login failed');
    } catch (e) {
      return Left(e.toString());
    }
  }

  @override
  Future<Either<String, TokenResponse>> register({
    required String email,
    required String username,
    required String password,
    required String fullName,
  }) async {
    try {
      final response = await _remoteDataSource.register(
        email: email,
        username: username,
        password: password,
        fullName: fullName,
      );
      await _localDataSource.saveTokens(
        accessToken: response.accessToken,
        refreshToken: response.refreshToken,
      );
      return Right(response);
    } on DioException catch (e) {
      return Left(
        e.response?.data['detail'] ?? e.message ?? 'Registration failed',
      );
    } catch (e) {
      return Left(e.toString());
    }
  }

  @override
  Future<Either<String, TokenResponse>> refresh({
    required String refreshToken,
  }) async {
    try {
      final response = await _remoteDataSource.refresh(
        refreshToken: refreshToken,
      );
      await _localDataSource.saveTokens(
        accessToken: response.accessToken,
        refreshToken: response.refreshToken,
      );
      return Right(response);
    } on DioException catch (e) {
      return Left(e.response?.data['detail'] ?? e.message ?? 'Refresh failed');
    } catch (e) {
      return Left(e.toString());
    }
  }

  @override
  Future<Either<String, void>> logout() async {
    try {
      await _localDataSource.clearTokens();
      return const Right(null);
    } catch (e) {
      return Left(e.toString());
    }
  }

  @override
  Future<bool> isAuthenticated() async {
    return _localDataSource.hasTokens();
  }

  @override
  Future<String?> getAccessToken() async {
    return _localDataSource.getAccessToken();
  }
}
