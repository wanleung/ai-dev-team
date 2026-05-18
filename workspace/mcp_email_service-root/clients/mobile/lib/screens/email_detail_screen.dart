import 'dart:io';

import 'package:flutter/material.dart';
import 'package:mcp_email_mobile/models/models.dart';
import 'package:mcp_email_mobile/providers/providers.dart';
import 'package:mcp_email_mobile/widgets/widgets.dart';
import 'package:open_file/open_file.dart';
import 'package:path_provider/path_provider.dart';
import 'package:provider/provider.dart';

class EmailDetailScreen extends StatefulWidget {
  final EmailMessage email;

  const EmailDetailScreen({super.key, required this.email});

  @override
  State<EmailDetailScreen> createState() => _EmailDetailScreenState();
}

class _EmailDetailScreenState extends State<EmailDetailScreen> {
  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      context.read<EmailProvider>().loadEmailDetail(widget.email.id);
      if (!widget.email.isRead) {
        context.read<EmailProvider>().markAsRead(widget.email.id, true);
      }
    });
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Email'),
        actions: [
          Consumer<EmailProvider>(
            builder: (context, provider, child) {
              final email = provider.selectedEmail ?? widget.email;
              return IconButton(
                icon: Icon(
                  email.isRead
                      ? Icons.mark_email_read
                      : Icons.mark_email_unread,
                ),
                onPressed: () {
                  provider.markAsRead(email.id, !email.isRead);
                },
              );
            },
          ),
        ],
      ),
      body: Consumer<EmailProvider>(
        builder: (context, emailProvider, child) {
          if (emailProvider.isLoading && emailProvider.selectedEmail == null) {
            return const LoadingIndicator(message: 'Loading email...');
          }

          if (emailProvider.selectedEmail == null &&
              emailProvider.error != null) {
            return Center(
              child: Column(
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  const Icon(Icons.error_outline, size: 48, color: Colors.red),
                  const SizedBox(height: 16),
                  Text('Error: ${emailProvider.error}'),
                ],
              ),
            );
          }

          final email = emailProvider.selectedEmail ?? widget.email;

          return Column(
            children: [
              Expanded(child: EmailDetailBody(email: email)),
              if (email.attachments != null && email.attachments!.isNotEmpty)
                AttachmentList(
                  attachments: email.attachments!,
                  onDownload: (attachmentId) =>
                      _downloadAttachment(email.id, attachmentId),
                ),
            ],
          );
        },
      ),
    );
  }

  Future<void> _downloadAttachment(int emailId, int attachmentId) async {
    final scaffoldMessenger = ScaffoldMessenger.of(context);
    scaffoldMessenger.showSnackBar(
      const SnackBar(content: Text('Downloading attachment...')),
    );

    try {
      final bytes = await context.read<EmailProvider>().downloadAttachment(
        emailId,
        attachmentId,
      );
      final dir = await getApplicationDocumentsDirectory();
      final file = File('${dir.path}/attachment_$attachmentId');
      await file.writeAsBytes(bytes);

      await OpenFile.open(file.path);
      scaffoldMessenger.showSnackBar(
        const SnackBar(content: Text('Attachment downloaded and opened')),
      );
    } catch (e) {
      scaffoldMessenger.showSnackBar(
        SnackBar(content: Text('Download failed: $e')),
      );
    }
  }
}
