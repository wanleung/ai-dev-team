import 'package:mcp_email_mobile/models/email_account.dart' show AttachmentInfo;

class EmailMessage {
  final int id;
  final int accountId;
  final int uid;
  final String messageId;
  final String subject;
  final String sender;
  final String recipients;
  final DateTime dateReceived;
  final String bodyText;
  final String bodyHtml;
  final bool hasAttachments;
  final bool isRead;
  final DateTime createdAt;
  final List<AttachmentInfo>? attachments;

  const EmailMessage({
    required this.id,
    required this.accountId,
    required this.uid,
    required this.messageId,
    required this.subject,
    required this.sender,
    required this.recipients,
    required this.dateReceived,
    required this.bodyText,
    required this.bodyHtml,
    required this.hasAttachments,
    required this.isRead,
    required this.createdAt,
    this.attachments,
  });

  factory EmailMessage.fromJson(Map<String, dynamic> json) {
    List<AttachmentInfo>? attachments;
    if (json['attachments'] != null && json['attachments'] is List) {
      attachments = (json['attachments'] as List)
          .map((a) => AttachmentInfo.fromJson(a as Map<String, dynamic>))
          .toList();
    }

    return EmailMessage(
      id: json['id'] as int,
      accountId: json['account_id'] as int,
      uid: json['uid'] as int,
      messageId: json['message_id'] as String,
      subject: json['subject'] as String? ?? '',
      sender: json['sender'] as String? ?? '',
      recipients: json['recipients'] as String? ?? '',
      dateReceived: DateTime.parse(json['date_received'] as String),
      bodyText: json['body_text'] as String? ?? '',
      bodyHtml: json['body_html'] as String? ?? '',
      hasAttachments: json['has_attachments'] as bool? ?? false,
      isRead: json['is_read'] as bool? ?? false,
      createdAt: DateTime.parse(json['created_at'] as String),
      attachments: attachments,
    );
  }

  Map<String, dynamic> toJson() {
    return {
      'id': id,
      'account_id': accountId,
      'uid': uid,
      'message_id': messageId,
      'subject': subject,
      'sender': sender,
      'recipients': recipients,
      'date_received': dateReceived.toIso8601String(),
      'body_text': bodyText,
      'body_html': bodyHtml,
      'has_attachments': hasAttachments,
      'is_read': isRead,
      'created_at': createdAt.toIso8601String(),
      if (attachments != null)
        'attachments': attachments!.map((a) => a.toJson()).toList(),
    };
  }

  EmailMessage copyWith({
    int? id,
    int? accountId,
    int? uid,
    String? messageId,
    String? subject,
    String? sender,
    String? recipients,
    DateTime? dateReceived,
    String? bodyText,
    String? bodyHtml,
    bool? hasAttachments,
    bool? isRead,
    DateTime? createdAt,
    List<AttachmentInfo>? attachments,
  }) {
    return EmailMessage(
      id: id ?? this.id,
      accountId: accountId ?? this.accountId,
      uid: uid ?? this.uid,
      messageId: messageId ?? this.messageId,
      subject: subject ?? this.subject,
      sender: sender ?? this.sender,
      recipients: recipients ?? this.recipients,
      dateReceived: dateReceived ?? this.dateReceived,
      bodyText: bodyText ?? this.bodyText,
      bodyHtml: bodyHtml ?? this.bodyHtml,
      hasAttachments: hasAttachments ?? this.hasAttachments,
      isRead: isRead ?? this.isRead,
      createdAt: createdAt ?? this.createdAt,
      attachments: attachments ?? this.attachments,
    );
  }
}
