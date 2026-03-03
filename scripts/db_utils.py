from src_utils.logsetup import setup_logging

logger = setup_logging(__name__)
"""
Утилиты для работы с системой модерации
"""
import csv
import json
from datetime import datetime

from core.models import AdminLog, Chat, Note, Punishment, SessionLocal, User


def export_users_to_csv(filename="users_export.csv"):
    """Экспорт пользователей в CSV"""
    db = SessionLocal()
    try:
        users = db.query(User).all()

        with open(filename, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(['ID', 'Username', 'First Name', 'Last Name', 'Created At', 'Total Punishments'])

            for user in users:
                punishments_count = len(user.punishments)
                writer.writerow([
                    user.id,
                    user.username or '',
                    user.first_name or '',
                    user.last_name or '',
                    user.created_at.strftime('%Y-%m-%d %H:%M:%S'),
                    punishments_count
                ])

        logger.info(f"✅ Пользователи экспортированы в {filename}")
        return True
    except Exception as e:
        logger.info(f"❌ Ошибка экспорта: {e}")
        return False
    finally:
        db.close()


def export_punishments_to_csv(filename="punishments_export.csv"):
    """Экспорт наказаний в CSV"""
    db = SessionLocal()
    try:
        punishments = db.query(Punishment).all()

        with open(filename, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow([
                'ID', 'User ID', 'Chat ID', 'Type', 'Reason',
                'Admin', 'Date', 'Until Date', 'Active'
            ])

            for p in punishments:
                writer.writerow([
                    p.id,
                    p.user_id,
                    p.chat_id,
                    p.type,
                    p.reason or '',
                    p.admin_name or '',
                    p.date.strftime('%Y-%m-%d %H:%M:%S'),
                    p.until_date.strftime('%Y-%m-%d %H:%M:%S') if p.until_date else '',
                    'Yes' if p.active else 'No'
                ])

        logger.info(f"✅ Наказания экспортированы в {filename}")
        return True
    except Exception as e:
        logger.info(f"❌ Ошибка экспорта: {e}")
        return False
    finally:
        db.close()


def export_all_to_json(filename="full_export.json"):
    """Полный экспорт всех данных в JSON"""
    db = SessionLocal()
    try:
        data = {
            'export_date': datetime.utcnow().isoformat(),
            'users': [],
            'chats': [],
            'punishments': [],
            'notes': []
        }

        # Пользователи
        for user in db.query(User).all():
            data['users'].append({
                'id': user.id,
                'username': user.username,
                'first_name': user.first_name,
                'last_name': user.last_name,
                'created_at': user.created_at.isoformat()
            })

        # Чаты
        for chat in db.query(Chat).all():
            data['chats'].append({
                'id': chat.id,
                'title': chat.title,
                'chat_type': chat.chat_type,
                'created_at': chat.created_at.isoformat()
            })

        # Наказания
        for p in db.query(Punishment).all():
            data['punishments'].append({
                'id': p.id,
                'user_id': p.user_id,
                'chat_id': p.chat_id,
                'type': p.type,
                'reason': p.reason,
                'admin_id': p.admin_id,
                'admin_name': p.admin_name,
                'date': p.date.isoformat(),
                'until_date': p.until_date.isoformat() if p.until_date else None,
                'active': p.active
            })

        # Заметки
        for note in db.query(Note).all():
            data['notes'].append({
                'id': note.id,
                'user_id': note.user_id,
                'content': note.content,
                'author_name': note.author_name,
                'created_at': note.created_at.isoformat()
            })

        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        logger.info(f"✅ Все данные экспортированы в {filename}")
        return True
    except Exception as e:
        logger.info(f"❌ Ошибка экспорта: {e}")
        return False
    finally:
        db.close()


def get_statistics():
    """Получает статистику системы"""
    db = SessionLocal()
    try:
        stats = {
            'total_users': db.query(User).count(),
            'total_chats': db.query(Chat).count(),
            'total_punishments': db.query(Punishment).count(),
            'active_punishments': db.query(Punishment).filter(Punishment.active == True).count(),
            'total_notes': db.query(Note).count(),
            'total_logs': db.query(AdminLog).count()
        }

        logger.info("\n📊 Статистика системы:")
        logger.info("=" * 40)
        for key, value in stats.items():
            logger.info(f"{key.replace('_', ' ').title()}: {value}")
        logger.info("=" * 40)

        return stats
    finally:
        db.close()


def cleanup_old_punishments(days=30):
    """Удаляет старые неактивные наказания"""
    db = SessionLocal()
    try:
        from datetime import timedelta
        cutoff_date = datetime.utcnow() - timedelta(days=days)

        old_punishments = db.query(Punishment).filter(
            Punishment.active == False,
            Punishment.date < cutoff_date
        ).all()

        count = len(old_punishments)
        for p in old_punishments:
            db.delete(p)

        db.commit()
        logger.info(f"✅ Удалено {count} старых наказаний (старше {days} дней)")
        return count
    except Exception as e:
        logger.info(f"❌ Ошибка очистки: {e}")
        db.rollback()
        return 0
    finally:
        db.close()


if __name__ == '__main__':
    try:
            import sys

            if len(sys.argv) < 2:
                logger.info("Использование:")
                logger.info("  python utils.py stats              - Показать статистику")
                logger.info("  python utils.py export_users       - Экспорт пользователей в CSV")
                logger.info("  python utils.py export_punishments - Экспорт наказаний в CSV")
                logger.info("  python utils.py export_json        - Полный экспорт в JSON")
                logger.info("  python utils.py cleanup [days]     - Очистка старых наказаний")
                sys.exit(1)

            command = sys.argv[1]

            if command == 'stats':
                get_statistics()
            elif command == 'export_users':
                export_users_to_csv()
            elif command == 'export_punishments':
                export_punishments_to_csv()
            elif command == 'export_json':
                export_all_to_json()
            elif command == 'cleanup':
                days = int(sys.argv[2]) if len(sys.argv) > 2 else 30
                cleanup_old_punishments(days)
            else:
                logger.info(f"❌ Неизвестная команда: {command}")
                sys.exit(1)

    except Exception as e:
        logger.exception('Необработанное исключение: %s', e)
