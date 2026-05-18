import 'package:flutter/material.dart';
import 'package:mcp_email_mobile/models/models.dart';

class AttachmentList extends StatelessWidget {
  final List<AttachmentInfo> attachments;
  final Future<void> Function(int attachmentId) onDownload;

  const AttachmentList({
    super.key,
    required this.attachments,
    required this.onDownload,
  });

  @override
  Widget build(BuildContext context) {
    if (attachments.isEmpty) return const SizedBox.shrink();

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const Divider(),
        Padding(
          padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
          child: Text(
            'Attachments (${attachments.length})',
            style: Theme.of(context).textTheme.titleSmall,
          ),
        ),
        ListView.builder(
          shrinkWrap: true,
          physics: const NeverScrollableScrollPhysics(),
          itemCount: attachments.length,
          itemBuilder: (context, index) {
            final attachment = attachments[index];
            return ListTile(
              leading: Icon(_getAttachmentIcon(attachment.contentType)),
              title: Text(attachment.filename),
              subtitle: Text(attachment.formattedSize),
              trailing: IconButton(
                icon: const Icon(Icons.download),
                onPressed: () => onDownload(attachment.id),
              ),
            );
          },
        ),
      ],
    );
  }

  IconData _getAttachmentIcon(String contentType) {
    if (contentType.startsWith('image/')) return Icons.image;
    if (contentType.contains('pdf')) return Icons.picture_as_pdf;
    if (contentType.contains('document') || contentType.contains('word'))
      return Icons.description;
    if (contentType.contains('spreadsheet') || contentType.contains('excel'))
      return Icons.table_chart;
    return Icons.attach_file;
  }
}
