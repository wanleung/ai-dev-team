import 'package:flutter/material.dart';
import 'package:flutter_html/flutter_html.dart';
import 'package:flutter_html/style.dart';
import 'package:mcp_email_mobile/models/models.dart';

class EmailDetailBody extends StatelessWidget {
  final EmailMessage email;

  const EmailDetailBody({super.key, required this.email});

  @override
  Widget build(BuildContext context) {
    final bodyToDisplay = email.bodyHtml.isNotEmpty
        ? email.bodyHtml
        : email.bodyText;

    return SingleChildScrollView(
      padding: const EdgeInsets.all(16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            email.subject.isNotEmpty ? email.subject : '(No subject)',
            style: Theme.of(context).textTheme.headlineSmall,
          ),
          const SizedBox(height: 16),
          _buildHeaderRow('From', email.sender),
          _buildHeaderRow('To', email.recipients),
          _buildHeaderRow('Date', email.dateReceived.toLocal().toString()),
          const Divider(height: 32),
          if (email.bodyHtml.isNotEmpty)
            Html(
              data: email.bodyHtml,
              style: {
                'body': Style(margin: Margins.zero, padding: HtmlPaddings.zero),
              },
            )
          else
            Text(email.bodyText, style: Theme.of(context).textTheme.bodyLarge),
        ],
      ),
    );
  }

  Widget _buildHeaderRow(String label, String value) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 8),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SizedBox(
            width: 60,
            child: Text(
              label,
              style: const TextStyle(fontWeight: FontWeight.bold),
            ),
          ),
          Expanded(
            child: Text(value, style: const TextStyle(color: Colors.black87)),
          ),
        ],
      ),
    );
  }
}
