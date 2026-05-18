import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../../../data/models/auth_models.dart';
import '../../../data/providers.dart';
import '../../../domain/repositories/auth_repository.dart';

class AuthNotifier extends AsyncNotifier<AuthState> {
  @override
  Future<AuthState> build() async {
    final repository = ref.watch(authRepositoryProvider);
    final isAuthenticated = await repository.isAuthenticated();
    if (isAuthenticated) {
      final accessToken = await repository.getAccessToken();
      return AuthState(isAuthenticated: true, accessToken: accessToken);
    }
    return const AuthState();
  }

  Future<void> login({required String email, required String password}) async {
    state = const AsyncValue.data(AuthState(isLoading: true));
    final repository = ref.read(authRepositoryProvider);
    final result = await repository.login(email: email, password: password);

    result.fold(
      (error) {
        state = AsyncValue.data(
          AuthState(isAuthenticated: false, error: error),
        );
      },
      (tokenResponse) {
        state = AsyncValue.data(
          AuthState(
            isAuthenticated: true,
            accessToken: tokenResponse.accessToken,
            refreshToken: tokenResponse.refreshToken,
          ),
        );
      },
    );
  }

  Future<void> register({
    required String email,
    required String username,
    required String password,
    required String fullName,
  }) async {
    state = const AsyncValue.data(AuthState(isLoading: true));
    final repository = ref.read(authRepositoryProvider);
    final result = await repository.register(
      email: email,
      username: username,
      password: password,
      fullName: fullName,
    );

    result.fold(
      (error) {
        state = AsyncValue.data(
          AuthState(isAuthenticated: false, error: error),
        );
      },
      (tokenResponse) {
        state = AsyncValue.data(
          AuthState(
            isAuthenticated: true,
            accessToken: tokenResponse.accessToken,
            refreshToken: tokenResponse.refreshToken,
          ),
        );
      },
    );
  }

  Future<void> refresh({required String refreshToken}) async {
    final repository = ref.read(authRepositoryProvider);
    final result = await repository.refresh(refreshToken: refreshToken);

    result.fold(
      (error) {
        state = AsyncValue.data(
          AuthState(isAuthenticated: false, error: error),
        );
      },
      (tokenResponse) {
        state = AsyncValue.data(
          AuthState(
            isAuthenticated: true,
            accessToken: tokenResponse.accessToken,
            refreshToken: tokenResponse.refreshToken,
          ),
        );
      },
    );
  }

  Future<void> logout() async {
    final repository = ref.read(authRepositoryProvider);
    await repository.logout();
    state = const AsyncValue.data(AuthState(isAuthenticated: false));
  }

  Future<void> checkAuthStatus() async {
    final repository = ref.read(authRepositoryProvider);
    final isAuthenticated = await repository.isAuthenticated();
    if (isAuthenticated) {
      final accessToken = await repository.getAccessToken();
      state = AsyncValue.data(
        AuthState(isAuthenticated: true, accessToken: accessToken),
      );
    } else {
      state = const AsyncValue.data(AuthState(isAuthenticated: false));
    }
  }
}

final authProvider = AsyncNotifierProvider<AuthNotifier, AuthState>(() {
  return AuthNotifier();
});
