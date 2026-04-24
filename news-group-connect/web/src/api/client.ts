/**
 * Typed API client for NewsGroup Connect backend.
 * Provides type-safe methods for all API endpoints.
 */

import axios, { type AxiosInstance, type AxiosRequestConfig } from 'axios';
import type {
  User,
  TokenResponse,
  Group,
  Post,
  Comment,
  Notification,
  GroupMembership,
  MediaFile,
  PaginatedResponse,
  LikeResponse,
  DeleteResponse,
  MembershipResponse,
  LeaveResponse,
  UploadResponse,
} from './types';

interface ApiClientConfig {
  baseURL?: string;
  timeout?: number;
}

const DEFAULT_CONFIG: Required<ApiClientConfig> = {
  baseURL: '/api/v1',
  timeout: 10000,
};

export class ApiClient {
  private client: AxiosInstance;
  private accessToken: string | null = null;
  private refreshToken: string | null = null;

  constructor(config: ApiClientConfig = {}) {
    const mergedConfig = { ...DEFAULT_CONFIG, ...config };
    this.client = axios.create(mergedConfig);

    this.client.interceptors.request.use((config) => {
      if (this.accessToken) {
        config.headers.Authorization = `Bearer ${this.accessToken}`;
      }
      return config;
    });

    this.client.interceptors.response.use(
      (response) => response,
      async (error) => {
        const originalRequest = error.config as AxiosRequestConfig & { _retry?: boolean };
        if (error.response?.status === 401 && !originalRequest._retry && this.refreshToken) {
          originalRequest._retry = true;
          try {
            const response = await this.refreshAccessToken();
            this.setTokens(response.access_token, response.refresh_token);
            if (originalRequest.headers) {
              originalRequest.headers.Authorization = `Bearer ${this.accessToken}`;
            }
            return this.client(originalRequest);
          } catch {
            this.clearTokens();
            window.location.href = '/login';
          }
        }
        return Promise.reject(error);
      }
    );
  }

  setTokens(accessToken: string, refreshToken: string): void {
    this.accessToken = accessToken;
    this.refreshToken = refreshToken;
    localStorage.setItem('access_token', accessToken);
    localStorage.setItem('refresh_token', refreshToken);
  }

  clearTokens(): void {
    this.accessToken = null;
    this.refreshToken = null;
    localStorage.removeItem('access_token');
    localStorage.removeItem('refresh_token');
  }

  loadTokensFromStorage(): void {
    const access = localStorage.getItem('access_token');
    const refresh = localStorage.getItem('refresh_token');
    if (access && refresh) {
      this.accessToken = access;
      this.refreshToken = refresh;
    }
  }

  async register(data: { email: string; username: string; password: string; full_name?: string }): Promise<{ user_id: number; token: string }> {
    const response = await this.client.post<{ user_id: number; token: string }>('/auth/register', data);
    return response.data;
  }

  async login(data: { email: string; password: string }): Promise<TokenResponse> {
    const response = await this.client.post<TokenResponse>('/auth/login', data);
    this.setTokens(response.data.access_token, response.data.refresh_token);
    return response.data;
  }

  async refreshAccessToken(): Promise<TokenResponse> {
    if (!this.refreshToken) {
      throw new Error('No refresh token available');
    }
    const response = await this.client.post<TokenResponse>('/auth/refresh', {
      refresh_token: this.refreshToken,
    });
    this.setTokens(response.data.access_token, response.data.refresh_token);
    return response.data;
  }

  async getUser(id: number): Promise<User> {
    const response = await this.client.get<User>(`/users/${id}`);
    return response.data;
  }

  async updateUser(id: number, data: { full_name?: string; avatar_url?: string }): Promise<User> {
    const response = await this.client.put<User>(`/users/${id}`, data);
    return response.data;
  }

  async deleteUser(id: number): Promise<DeleteResponse> {
    const response = await this.client.delete<DeleteResponse>(`/users/${id}`);
    return response.data;
  }

  async verifyEmail(data: { email: string; token: string }): Promise<{ verified: boolean }> {
    const response = await this.client.post<{ verified: boolean }>('/users/verify-email', data);
    return response.data;
  }

  async getPosts(params?: { page?: number; limit?: number; category?: string; group_id?: number; author_id?: number }): Promise<PaginatedResponse<Post>> {
    const response = await this.client.get<PaginatedResponse<Post>>('/posts', { params });
    return response.data;
  }

  async getPost(id: number): Promise<Post> {
    const response = await this.client.get<Post>(`/posts/${id}`);
    return response.data;
  }

  async createPost(data: { title: string; content: string; category: string; group_id?: number }): Promise<Post> {
    const response = await this.client.post<Post>('/posts', data);
    return response.data;
  }

  async updatePost(id: number, data: { title?: string; content?: string; category?: string }): Promise<Post> {
    const response = await this.client.put<Post>(`/posts/${id}`, data);
    return response.data;
  }

  async deletePost(id: number): Promise<DeleteResponse> {
    const response = await this.client.delete<DeleteResponse>(`/posts/${id}`);
    return response.data;
  }

  async likePost(id: number): Promise<LikeResponse> {
    const response = await this.client.post<LikeResponse>(`/posts/${id}/like`);
    return response.data;
  }

  async getGroups(params?: { page?: number; limit?: number; is_public?: boolean }): Promise<PaginatedResponse<Group>> {
    const response = await this.client.get<PaginatedResponse<Group>>('/groups', { params });
    return response.data;
  }

  async getGroup(id: number): Promise<Group & { members: GroupMembership[] }> {
    const response = await this.client.get<Group & { members: GroupMembership[] }>(`/groups/${id}`);
    return response.data;
  }

  async createGroup(data: { name: string; description: string; is_public: boolean }): Promise<Group> {
    const response = await this.client.post<Group>('/groups', data);
    return response.data;
  }

  async updateGroup(id: number, data: { name?: string; description?: string; is_public?: boolean }): Promise<Group> {
    const response = await this.client.put<Group>(`/groups/${id}`, data);
    return response.data;
  }

  async deleteGroup(id: number): Promise<DeleteResponse> {
    const response = await this.client.delete<DeleteResponse>(`/groups/${id}`);
    return response.data;
  }

  async joinGroup(id: number): Promise<MembershipResponse> {
    const response = await this.client.post<MembershipResponse>(`/groups/${id}/join`);
    return response.data;
  }

  async leaveGroup(id: number): Promise<LeaveResponse> {
    const response = await this.client.post<LeaveResponse>(`/groups/${id}/leave`);
    return response.data;
  }

  async getComments(params: { post_id: number; page?: number; limit?: number }): Promise<PaginatedResponse<Comment>> {
    const response = await this.client.get<PaginatedResponse<Comment>>('/comments', { params });
    return response.data;
  }

  async createComment(data: { post_id: number; content: string; parent_id?: number }): Promise<Comment> {
    const response = await this.client.post<Comment>('/comments', data);
    return response.data;
  }

  async deleteComment(id: number): Promise<DeleteResponse> {
    const response = await this.client.delete<DeleteResponse>(`/comments/${id}`);
    return response.data;
  }

  async getNotifications(params?: { page?: number; limit?: number; unread_only?: boolean }): Promise<PaginatedResponse<Notification>> {
    const response = await this.client.get<PaginatedResponse<Notification>>('/notifications', { params });
    return response.data;
  }

  async markNotificationRead(id: number): Promise<Notification> {
    const response = await this.client.post<Notification>(`/notifications/${id}/read`);
    return response.data;
  }

  async markAllNotificationsRead(): Promise<{ marked_count: number }> {
    const response = await this.client.post<{ marked_count: number }>('/notifications/read-all');
    return response.data;
  }

  async uploadMedia(file: File): Promise<UploadResponse> {
    const formData = new FormData();
    formData.append('file', file);
    const response = await this.client.post<UploadResponse>('/media/upload', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    });
    return response.data;
  }

  async getMedia(params?: { page?: number; limit?: number }): Promise<PaginatedResponse<MediaFile>> {
    const response = await this.client.get<PaginatedResponse<MediaFile>>('/media', { params });
    return response.data;
  }

  async getMediaById(id: number): Promise<MediaFile> {
    const response = await this.client.get<MediaFile>(`/media/${id}`);
    return response.data;
  }

  async deleteMedia(id: number): Promise<DeleteResponse> {
    const response = await this.client.delete<DeleteResponse>(`/media/${id}`);
    return response.data;
  }
}

export const apiClient = new ApiClient();
