/**
 * TypeScript interfaces for NewsGroup Connect API entities.
 * These types mirror the backend Pydantic response schemas.
 */

export interface User {
  id: number;
  email: string;
  username: string;
  full_name: string | null;
  avatar_url: string | null;
  is_verified: boolean;
  created_at: string;
  updated_at: string;
}

export interface TokenResponse {
  access_token: string;
  refresh_token: string;
  token_type: string;
}

export interface Group {
  id: number;
  name: string;
  description: string;
  owner_id: number;
  is_public: boolean;
  member_count: number;
  created_at: string;
  updated_at: string;
}

export interface Post {
  id: number;
  title: string;
  content: string;
  author_id: number;
  author?: User;
  group_id: number | null;
  group?: Group;
  category: string;
  image_url: string | null;
  view_count: number;
  like_count: number;
  created_at: string;
  updated_at: string;
}

export interface Comment {
  id: number;
  post_id: number;
  author_id: number;
  author?: User;
  content: string;
  parent_id: number | null;
  replies?: Comment[];
  like_count: number;
  created_at: string;
  updated_at: string;
}

export interface Notification {
  id: number;
  user_id: number;
  type: 'push' | 'email' | 'in_app';
  title: string;
  message: string;
  is_read: boolean;
  created_at: string;
}

export interface GroupMembership {
  id: number;
  group_id: number;
  user_id: number;
  role: 'admin' | 'member' | 'moderator';
  joined_at: string;
  is_active: boolean;
}

export interface MediaFile {
  id: number;
  filename: string;
  original_filename: string;
  content_type: string;
  size: number;
  url: string;
  thumbnail_url: string | null;
  uploaded_by: number;
  created_at: string;
}

export interface PaginatedResponse<T> {
  items: T[];
  total: number;
  page: number;
  limit: number;
  has_next: boolean;
  has_prev: boolean;
}

export interface LikeResponse {
  like_count: number;
}

export interface DeleteResponse {
  deleted: boolean;
}

export interface MembershipResponse {
  membership: GroupMembership;
}

export interface LeaveResponse {
  left: boolean;
}

export interface UploadResponse {
  id: number;
  url: string;
  filename: string;
}
