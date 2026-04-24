import 'package:flutter/material.dart';
import 'package:intl/intl.dart';
import 'package:mcp_email_mobile/models/models.dart';

class EmailListItem extends StatelessWidget {
  final EmailMessage email;
  final VoidCallback onTap;

  const EmailListItem({super.key, required this.email, required this.onTap});

  @override
  Widget build(BuildContext context) {
    final dateFormat = DateFormat('MMM d, yyyy HH:mm');
    final formattedDate = dateFormat.format(email.dateReceived.toLocal());

    return ListTile(
      leading: CircleAvatar(
        backgroundColor: email.isRead
            ? Colors.grey[300]
            : Theme.of(context).primaryColor,
        child: Text(
          email.sender.isNotEmpty ? email.sender[0].toUpperCase() : '?',
          style: TextStyle(
            color: email.isRead ? Colors.grey[700] : Colors.white,
            fontWeight: FontWeight.bold,
          ),
        ),
      ),
      title: Row(
        children: [
          Expanded(
            child: Text(
              email.sender,
              style: TextStyle(
                fontWeight: email.isRead ? FontWeight.normal : FontWeight.bold,
              ),
              overflow: TextOverflow.ellipsis,
            ),
          ),
          if (email.hasAttachments)
            const Icon(Icons.attach_file, size: 16, color: Colors.grey),
        ],
      ),
      subtitle: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            email.subject.isNotEmpty ? email.subject : '(No subject)',
            style: TextStyle(
              fontWeight: email.isRead ? FontWeight.normal : FontWeight.bold,
            ),
            maxLines: 1,
            overflow: TextOverflow.ellipsis,
          ),
          const SizedBox(height: 4),
          Text(
            email.bodyText.isNotEmpty
                ? email.bodyText.substring(
                    0,
                    email.bodyText.length.clamp(0, 80),
                  )
                : '',
            maxLines: 1,
            overflow: TextOverflow.ellipsis,
            style: TextStyle(color: Colors.grey[600], fontSize: 12),
          ),
        ],
      ),
      trailing: Text(
        formattedDate,
        style: TextStyle(color: Colors.grey[600], fontSize: 12),
      ),
      onTap: onTap,
    );
  }
}
