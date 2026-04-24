import 'package:flutter/material.dart';
import 'package:mcp_email_mobile/models/models.dart';
import 'package:mcp_email_mobile/providers/providers.dart';
import 'package:mcp_email_mobile/widgets/widgets.dart';
import 'package:provider/provider.dart';

class EmailListScreen extends StatefulWidget {
  final EmailAccount account;

  const EmailListScreen({super.key, required this.account});

  @override
  State<EmailListScreen> createState() => _EmailListScreenState();
}

class _EmailListScreenState extends State<EmailListScreen> {
  final ScrollController _scrollController = ScrollController();
  final TextEditingController _searchController = TextEditingController();
  String? _searchQuery;

  @override
  void initState() {
    super.initState();
    _scrollController.addListener(_onScroll);
    WidgetsBinding.instance.addPostFrameCallback((_) {
      _loadEmails(refresh: true);
    });
  }

  @override
  void dispose() {
    _scrollController.dispose();
    _searchController.dispose();
    super.dispose();
  }

  void _onScroll() {
    if (_scrollController.position.pixels >=
        _scrollController.position.maxScrollExtent - 200) {
      _loadEmails();
    }
  }

  Future<void> _loadEmails({bool refresh = false}) {
    return context.read<EmailProvider>().loadEmails(
      accountId: widget.account.id,
      search: _searchQuery,
      refresh: refresh,
    );
  }

  void _onSearch(String query) {
    setState(() {
      _searchQuery = query.isEmpty ? null : query;
    });
    _loadEmails(refresh: true);
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(widget.account.emailAddress),
            Text(
              'Emails',
              style: Theme.of(
                context,
              ).textTheme.bodySmall?.copyWith(color: Colors.white70),
            ),
          ],
        ),
        actions: [
          IconButton(
            icon: const Icon(Icons.refresh),
            onPressed: () => _loadEmails(refresh: true),
          ),
        ],
        bottom: PreferredSize(
          preferredSize: const Size.fromHeight(48),
          child: Padding(
            padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
            child: TextField(
              controller: _searchController,
              decoration: InputDecoration(
                hintText: 'Search emails...',
                prefixIcon: const Icon(Icons.search),
                suffixIcon: _searchQuery != null
                    ? IconButton(
                        icon: const Icon(Icons.clear),
                        onPressed: () {
                          _searchController.clear();
                          _onSearch('');
                        },
                      )
                    : null,
                border: OutlineInputBorder(
                  borderRadius: BorderRadius.circular(24),
                ),
                contentPadding: const EdgeInsets.symmetric(horizontal: 16),
              ),
              onSubmitted: _onSearch,
            ),
          ),
        ),
      ),
      body: Consumer<EmailProvider>(
        builder: (context, emailProvider, child) {
          if (emailProvider.isLoading && emailProvider.emails.isEmpty) {
            return const LoadingIndicator(message: 'Loading emails...');
          }

          if (emailProvider.emails.isEmpty) {
            return Center(
              child: Column(
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  const Icon(
                    Icons.inbox_outlined,
                    size: 64,
                    color: Colors.grey,
                  ),
                  const SizedBox(height: 16),
                  const Text('No emails found'),
                ],
              ),
            );
          }

          return RefreshIndicator(
            onRefresh: () => _loadEmails(refresh: true),
            child: ListView.builder(
              controller: _scrollController,
              itemCount:
                  emailProvider.emails.length +
                  (emailProvider.isLoading ? 1 : 0),
              itemBuilder: (context, index) {
                if (index == emailProvider.emails.length) {
                  return const Padding(
                    padding: EdgeInsets.all(16),
                    child: Center(child: CircularProgressIndicator()),
                  );
                }

                final email = emailProvider.emails[index];
                return EmailListItem(
                  email: email,
                  onTap: () => _openEmailDetail(email),
                );
              },
            ),
          );
        },
      ),
    );
  }

  void _openEmailDetail(EmailMessage email) {
    Navigator.pushNamed(context, '/email-detail', arguments: email);
  }
}
