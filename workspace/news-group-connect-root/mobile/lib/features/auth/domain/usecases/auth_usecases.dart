import 'package:dartz/dartz.dart';
import '../../data/models/auth_models.dart';

class LoginUseCase {
  final Future<Either<String, TokenResponse>> Function({
    required String email,
    required String password,
  })
  call;

  const LoginUseCase({required this.call});
}

class RegisterUseCase {
  final Future<Either<String, TokenResponse>> Function({
    required String email,
    required String username,
    required String password,
    required String fullName,
  })
  call;

  const RegisterUseCase({required this.call});
}

class RefreshTokenUseCase {
  final Future<Either<String, TokenResponse>> Function({
    required String refreshToken,
  })
  call;

  const RefreshTokenUseCase({required this.call});
}

class LogoutUseCase {
  final Future<Either<String, void>> Function() call;

  const LogoutUseCase({required this.call});
}

class IsAuthenticatedUseCase {
  final Future<bool> Function() call;

  const IsAuthenticatedUseCase({required this.call});
}
