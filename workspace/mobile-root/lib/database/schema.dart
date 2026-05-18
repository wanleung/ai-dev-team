import 'package:drift/drift.dart';

part 'schema.g.dart';

class Users extends Table {
  IntColumn get id => integer().autoIncrement()();
  TextColumn get email => text().withLength(min: 1, max: 255)();
  TextColumn get username => text().withLength(min: 1, max: 50)();
  TextColumn get passwordHash => text()();
  TextColumn get fullName => text().withLength(min: 1, max: 100)();
  TextColumn get avatarUrl => text().nullable()();
  BoolColumn get isVerified => boolean().withDefault(const Constant(false))();
  DateTimeColumn get createdAt => dateTime().withDefault(currentDateAndTime)();
  DateTimeColumn get updatedAt => dateTime().withDefault(currentDateAndTime)();
}

class Groups extends Table {
  IntColumn get id => integer().autoIncrement()();
  TextColumn get name => text().withLength(min: 1, max: 100)();
  TextColumn get description => text().withLength(min: 1, max: 500)();
  IntColumn get ownerId => integer()();
  BoolColumn get isPublic => boolean().withDefault(const Constant(true))();
  IntColumn get memberCount => integer().withDefault(const Constant(0))();
  DateTimeColumn get createdAt => dateTime().withDefault(currentDateAndTime)();
  DateTimeColumn get updatedAt => dateTime().withDefault(currentDateAndTime)();
}

class Posts extends Table {
  IntColumn get id => integer().autoIncrement()();
  TextColumn get title => text().withLength(min: 1, max: 200)();
  TextColumn get content => text()();
  IntColumn get authorId => integer()();
  IntColumn get groupId => integer().nullable()();
  TextColumn get category => text().withLength(min: 1, max: 50)();
  TextColumn get imageUrl => text().nullable()();
  IntColumn get viewCount => integer().withDefault(const Constant(0))();
  IntColumn get likeCount => integer().withDefault(const Constant(0))();
  DateTimeColumn get createdAt => dateTime().withDefault(currentDateAndTime)();
  DateTimeColumn get updatedAt => dateTime().withDefault(currentDateAndTime)();
}

class Comments extends Table {
  IntColumn get id => integer().autoIncrement()();
  IntColumn get postId => integer()();
  IntColumn get authorId => integer()();
  TextColumn get content => text()();
  IntColumn get parentId => integer().nullable()();
  IntColumn get likeCount => integer().withDefault(const Constant(0))();
  DateTimeColumn get createdAt => dateTime().withDefault(currentDateAndTime)();
  DateTimeColumn get updatedAt => dateTime().withDefault(currentDateAndTime)();
}

class GroupMemberships extends Table {
  IntColumn get id => integer().autoIncrement()();
  IntColumn get groupId => integer()();
  IntColumn get userId => integer()();
  TextColumn get role => textEnum<GroupRole>()();
  BoolColumn get isActive => boolean().withDefault(const Constant(true))();
  DateTimeColumn get joinedAt => dateTime().withDefault(currentDateAndTime)();
}

class Notifications extends Table {
  IntColumn get id => integer().autoIncrement()();
  IntColumn get userId => integer()();
  TextColumn get type => textEnum<NotificationType>()();
  TextColumn get title => text().withLength(min: 1, max: 100)();
  TextColumn get message => text()();
  BoolColumn get isRead => boolean().withDefault(const Constant(false))();
  DateTimeColumn get createdAt => dateTime().withDefault(currentDateAndTime)();
}

class MediaFiles extends Table {
  IntColumn get id => integer().autoIncrement()();
  TextColumn get filename => text()();
  TextColumn get url => text()();
  TextColumn get thumbnailUrl => text().nullable()();
  TextColumn get contentType => text()();
  IntColumn get size => integer()();
  IntColumn get uploadedBy => integer()();
  DateTimeColumn get createdAt => dateTime().withDefault(currentDateAndTime)();
}

enum GroupRole { admin, member, moderator }

enum NotificationType { push, email, inApp }

@DriftDatabase(
  tables: [
    Users,
    Groups,
    Posts,
    Comments,
    GroupMemberships,
    Notifications,
    MediaFiles,
  ],
)
class AppDatabase extends _$AppDatabase {
  AppDatabase(super.e);

  @override
  int get schemaVersion => 1;

  // --- Users ---

  Future<int> insertUser(UsersCompanion user) {
    return into(users).insert(user);
  }

  Future<User?> getUserById(int id) {
    return (select(users)..where((u) => u.id.equals(id))).getSingleOrNull();
  }

  Future<User?> getUserByEmail(String email) {
    return (select(
      users,
    )..where((u) => u.email.equals(email))).getSingleOrNull();
  }

  Future<User?> getUserByUsername(String username) {
    return (select(
      users,
    )..where((u) => u.username.equals(username))).getSingleOrNull();
  }

  Future<List<User>> getAllUsers() {
    return select(users).get();
  }

  Future<bool> updateUser(int id, UsersCompanion user) {
    return (update(users)..where((u) => u.id.equals(id))).write(user);
  }

  Future<int> deleteUser(int id) {
    return (delete(users)..where((u) => u.id.equals(id))).go();
  }

  // --- Groups ---

  Future<int> insertGroup(GroupsCompanion group) {
    return into(groups).insert(group);
  }

  Future<Group?> getGroupById(int id) {
    return (select(groups)..where((g) => g.id.equals(id))).getSingleOrNull();
  }

  Future<List<Group>> getAllGroups({bool? isPublic}) {
    final query = select(groups);
    if (isPublic != null) {
      query.where((g) => g.isPublic.equals(isPublic));
    }
    return query.get();
  }

  Future<bool> updateGroup(int id, GroupsCompanion group) {
    return (update(groups)..where((g) => g.id.equals(id))).write(group);
  }

  Future<int> deleteGroup(int id) {
    return (delete(groups)..where((g) => g.id.equals(id))).go();
  }

  // --- Posts ---

  Future<int> insertPost(PostsCompanion post) {
    return into(posts).insert(post);
  }

  Future<Post?> getPostById(int id) {
    return (select(posts)..where((p) => p.id.equals(id))).getSingleOrNull();
  }

  Future<List<Post>> getAllPosts({String? category, int? groupId}) {
    final query = select(posts);
    if (category != null) {
      query.where((p) => p.category.equals(category));
    }
    if (groupId != null) {
      query.where((p) => p.groupId.equals(groupId));
    }
    return query.get();
  }

  Future<bool> updatePost(int id, PostsCompanion post) {
    return (update(posts)..where((p) => p.id.equals(id))).write(post);
  }

  Future<int> deletePost(int id) {
    return (delete(posts)..where((p) => p.id.equals(id))).go();
  }

  Future<int> incrementViewCount(int id) {
    return (update(posts)..where((p) => p.id.equals(id))).write(
      const PostsCompanion(viewCount: Value.increase(1)),
    );
  }

  Future<int> incrementLikeCount(int id) {
    return (update(posts)..where((p) => p.id.equals(id))).write(
      const PostsCompanion(likeCount: Value.increase(1)),
    );
  }

  // --- Comments ---

  Future<int> insertComment(CommentsCompanion comment) {
    return into(comments).insert(comment);
  }

  Future<List<Comment>> getCommentsByPostId(int postId) {
    return (select(comments)..where((c) => c.postId.equals(postId))).get();
  }

  Future<Comment?> getCommentById(int id) {
    return (select(comments)..where((c) => c.id.equals(id))).getSingleOrNull();
  }

  Future<List<Comment>> getReplies(int parentId) {
    return (select(comments)..where((c) => c.parentId.equals(parentId))).get();
  }

  Future<int> deleteComment(int id) {
    return (delete(comments)..where((c) => c.id.equals(id))).go();
  }

  // --- Group Memberships ---

  Future<int> insertMembership(GroupMembershipsCompanion membership) {
    return into(groupMemberships).insert(membership);
  }

  Future<GroupMembership?> getMembership(int groupId, int userId) {
    return (select(groupMemberships)..where(
          (m) =>
              m.groupId.equals(groupId) &
              m.userId.equals(userId) &
              m.isActive.equals(true),
        ))
        .getSingleOrNull();
  }

  Future<List<GroupMembership>> getMembershipsByUserId(int userId) {
    return (select(
      groupMemberships,
    )..where((m) => m.userId.equals(userId) & m.isActive.equals(true))).get();
  }

  Future<List<GroupMembership>> getMembershipsByGroupId(int groupId) {
    return (select(
      groupMemberships,
    )..where((m) => m.groupId.equals(groupId) & m.isActive.equals(true))).get();
  }

  Future<bool> updateMembership(int id, GroupMembershipsCompanion membership) {
    return (update(
      groupMemberships,
    )..where((m) => m.id.equals(id))).write(membership);
  }

  Future<int> deleteMembership(int id) {
    return (delete(groupMemberships)..where((m) => m.id.equals(id))).go();
  }

  // --- Notifications ---

  Future<int> insertNotification(NotificationsCompanion notification) {
    return into(notifications).insert(notification);
  }

  Future<List<Notification>> getNotificationsByUserId(
    int userId, {
    bool? unreadOnly,
  }) {
    final query = select(notifications)..where((n) => n.userId.equals(userId));
    if (unreadOnly == true) {
      query.where((n) => n.isRead.equals(false));
    }
    return query.get();
  }

  Future<bool> markNotificationAsRead(int id) {
    return (update(notifications)..where((n) => n.id.equals(id))).write(
      const NotificationsCompanion(isRead: Value(true)),
    );
  }

  Future<int> markAllNotificationsAsRead(int userId) {
    return (update(notifications)
          ..where((n) => n.userId.equals(userId) & n.isRead.equals(false)))
        .write(const NotificationsCompanion(isRead: Value(true)));
  }

  Future<int> deleteNotification(int id) {
    return (delete(notifications)..where((n) => n.id.equals(id))).go();
  }

  // --- Media Files ---

  Future<int> insertMediaFile(MediaFilesCompanion mediaFile) {
    return into(mediaFiles).insert(mediaFile);
  }

  Future<MediaFile?> getMediaFileById(int id) {
    return (select(
      mediaFiles,
    )..where((m) => m.id.equals(id))).getSingleOrNull();
  }

  Future<List<MediaFile>> getMediaFilesByUserId(int userId) {
    return (select(
      mediaFiles,
    )..where((m) => m.uploadedBy.equals(userId))).get();
  }

  Future<int> deleteMediaFile(int id) {
    return (delete(mediaFiles)..where((m) => m.id.equals(id))).go();
  }
}
