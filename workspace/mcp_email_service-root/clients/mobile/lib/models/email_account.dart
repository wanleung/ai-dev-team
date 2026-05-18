import 'package:flutter/foundation.dart';

class EmailAccount {
  final int id;
  final String userId;
  final String emailAddress;
  final String imapHost;
  final int imapPort;
  final String username;
  final bool isActive;
  final DateTime createdAt;
  final DateTime updatedAt;

  const EmailAccount({
    required this.id,
    required this.userId,
    required this.emailAddress,
    required this.imapHost,
    required this.imapPort,
    required this.username,
    required this.isActive,
    required this.createdAt,
    required this.updatedAt,
  });

  factory EmailAccount.fromJson(Map<String, dynamic> json) {
    return EmailAccount(
      id: json['id'] as int,
      userId: json['user_id'] as String,
      emailAddress: json['email_address'] as String,
      imapHost: json['imap_host'] as String,
      imapPort: json['imap_port'] as int,
      username: json['username'] as String,
      isActive: json['is_active'] as bool? ?? true,
      createdAt: DateTime.parse(json['created_at'] as String),
      updatedAt: DateTime.parse(json['updated_at'] as String),
    );
  }

  Map<String, dynamic> toJson() {
    return {
      'id': id,
      'user_id': userId,
      'email_address': emailAddress,
      'imap_host': imapHost,
      'imap_port': imapPort,
      'username': username,
      'is_active': isActive,
      'created_at': createdAt.toIso8601String(),
      'updated_at': updatedAt.toIso8601String(),
    };
  }

  EmailAccount copyWith({
    int? id,
    String? userId,
    String? emailAddress,
    String? imapHost,
    int? imapPort,
    String? username,
    bool? isActive,
    DateTime? createdAt,
    DateTime? updatedAt,
  }) {
    return EmailAccount(
      id: id ?? this.id,
      userId: userId ?? this.userId,
      emailAddress: emailAddress ?? this.emailAddress,
      imapHost: imapHost ?? this.imapHost,
      imapPort: imapPort ?? this.imapPort,
      username: username ?? this.username,
      isActive: isActive ?? this.isActive,
      createdAt: createdAt ?? this.createdAt,
      updatedAt: updatedAt ?? this.updatedAt,
    );
  }
}

class AttachmentInfo {
  final int id;
  final int messageId;
  final String filename;
  final String contentType;
  final int sizeBytes;
  final String storagePath;

  const AttachmentInfo({
    required this.id,
    required this.messageId,
    required this.filename,
    required this.contentType,
    required this.sizeBytes,
    required this.storagePath,
  });

  factory AttachmentInfo.fromJson(Map<String, dynamic> json) {
    return AttachmentInfo(
      id: json['id'] as int,
      messageId: json['message_id'] as int,
      filename: json['filename'] as String,
      contentType: json['content_type'] as String,
      sizeBytes: json['size_bytes'] as int,
      storagePath: json['storage_path'] as String,
    );
  }

  Map<String, dynamic> toJson() {
    return {
      'id': id,
      'message_id': messageId,
      'filename': filename,
      'content_type': contentType,
      'size_bytes': sizeBytes,
      'storage_path': storagePath,
    };
  }

  String get formattedSize {
    if (sizeBytes < 1024) return '$sizeBytes B';
    if (sizeBytes < 1024 * 1024)
      return '${(sizeBytes / 1024).toStringAsFixed(1)} KB';
    return '${(sizeBytes / (1024 * 1024)).toStringAsFixed(1)} MB';
  }
}
