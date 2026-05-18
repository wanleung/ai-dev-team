import 'package:flutter/material.dart';
import 'package:mcp_email_mobile/models/models.dart';
import 'package:mcp_email_mobile/providers/providers.dart';
import 'package:provider/provider.dart';

class AccountListScreen extends StatefulWidget {
  const AccountListScreen({super.key});

  @override
  State<AccountListScreen> createState() => _AccountListScreenState();
}

class _AccountListScreenState extends State<AccountListScreen> {
  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      context.read<AccountProvider>().loadAccounts();
    });
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Email Accounts'),
        actions: [
          IconButton(
            icon: const Icon(Icons.add),
            onPressed: () => _showAddAccountDialog(context),
          ),
        ],
      ),
      body: Consumer<AccountProvider>(
        builder: (context, accountProvider, child) {
          if (accountProvider.isLoading && accountProvider.accounts.isEmpty) {
            return const Center(child: CircularProgressIndicator());
          }

          if (accountProvider.accounts.isEmpty) {
            return Center(
              child: Column(
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  const Icon(
                    Icons.email_outlined,
                    size: 64,
                    color: Colors.grey,
                  ),
                  const SizedBox(height: 16),
                  const Text('No email accounts configured'),
                  const SizedBox(height: 8),
                  ElevatedButton(
                    onPressed: () => _showAddAccountDialog(context),
                    child: const Text('Add Account'),
                  ),
                ],
              ),
            );
          }

          return ListView.builder(
            itemCount: accountProvider.accounts.length,
            itemBuilder: (context, index) {
              final account = accountProvider.accounts[index];
              return ListTile(
                leading: CircleAvatar(
                  child: Text(account.emailAddress[0].toUpperCase()),
                ),
                title: Text(account.emailAddress),
                subtitle: Text('${account.imapHost}:${account.imapPort}'),
                trailing: Row(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    IconButton(
                      icon: const Icon(Icons.sync),
                      onPressed: () => _syncAccount(context, account),
                    ),
                    IconButton(
                      icon: const Icon(Icons.delete_outline),
                      onPressed: () => _deleteAccount(context, account),
                    ),
                  ],
                ),
                onTap: () {
                  Navigator.pushNamed(context, '/emails', arguments: account);
                },
              );
            },
          );
        },
      ),
    );
  }

  void _showAddAccountDialog(BuildContext context) {
    final emailController = TextEditingController();
    final hostController = TextEditingController();
    final portController = TextEditingController(text: '993');
    final usernameController = TextEditingController();
    final passwordController = TextEditingController();

    showDialog(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Add Email Account'),
        content: SingleChildScrollView(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              TextField(
                controller: emailController,
                decoration: const InputDecoration(labelText: 'Email Address'),
                keyboardType: TextInputType.emailAddress,
              ),
              TextField(
                controller: hostController,
                decoration: const InputDecoration(labelText: 'IMAP Host'),
              ),
              TextField(
                controller: portController,
                decoration: const InputDecoration(labelText: 'IMAP Port'),
                keyboardType: TextInputType.number,
              ),
              TextField(
                controller: usernameController,
                decoration: const InputDecoration(labelText: 'Username'),
              ),
              TextField(
                controller: passwordController,
                decoration: const InputDecoration(labelText: 'Password'),
                obscureText: true,
              ),
            ],
          ),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context),
            child: const Text('Cancel'),
          ),
          ElevatedButton(
            onPressed: () {
              context.read<AccountProvider>().addAccount(
                emailAddress: emailController.text,
                imapHost: hostController.text,
                imapPort: int.tryParse(portController.text) ?? 993,
                username: usernameController.text,
                password: passwordController.text,
              );
              Navigator.pop(context);
            },
            child: const Text('Add'),
          ),
        ],
      ),
    );
  }

  Future<void> _syncAccount(BuildContext context, EmailAccount account) async {
    final scaffoldMessenger = ScaffoldMessenger.of(context);
    try {
      final result = await context.read<AccountProvider>().triggerSync(
        account.id,
      );
      scaffoldMessenger.showSnackBar(
        SnackBar(
          content: Text('Sync complete: ${result['messages_synced']} messages'),
        ),
      );
    } catch (e) {
      scaffoldMessenger.showSnackBar(
        SnackBar(content: Text('Sync failed: $e')),
      );
    }
  }

  Future<void> _deleteAccount(
    BuildContext context,
    EmailAccount account,
  ) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Delete Account'),
        content: Text(
          'Are you sure you want to delete ${account.emailAddress}?',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('Cancel'),
          ),
          TextButton(
            onPressed: () => Navigator.pop(context, true),
            child: const Text('Delete'),
          ),
        ],
      ),
    );

    if (confirmed == true) {
      await context.read<AccountProvider>().removeAccount(account.id);
    }
  }
}
