import pymysql

print("=" * 50)
print("🔍 ПРОВЕРКА НА ВРЪЗКАТА С БАЗАТА ДАННИ")
print("=" * 50)

# Данни за връзка
host = 'localhost'
port = 3307  # ← ТВОЯТ ПОРТ
user = 'root'
password = ''
database = 'register_user'

print(f"\n📊 Детайли за връзката:")
print(f"   • Хост: {host}")
print(f"   • Порт: {port}")
print(f"   • Потребител: {user}")
print(f"   • Парола: {'***' if password else '(празна)'}")
print(f"   • База: {database}")

print("\n🔄 Опит за свързване...")

try:
    # Опит за връзка
    connection = pymysql.connect(
        host='localhost',
        port=3307,
        user='root',
        password='',
        database='register_user',
        connect_timeout=5
    )

    print("✅ УСПЕШНА ВРЪЗКА!")

    # Проверка на таблиците
    with connection.cursor() as cursor:
        cursor.execute("SHOW TABLES")
        tables = cursor.fetchall()
        print(f"\n📋 Таблици в базата '{database}':")
        if tables:
            for table in tables:
                print(f"   • {table[0]}")
        else:
            print("   ❌ Няма таблици в базата!")

    # Затваряне на връзката
    connection.close()
    print("\n✅ Връзката затворена.")

except pymysql.err.OperationalError as e:
    print(f"\n❌ ГРЕШКА ПРИ ВРЪЗКА:")
    print(f"   {e}")
    print("\n🔧 Възможни причини:")
    print("   1. MySQL сървърът не е пуснат (провери XAMPP/WAMP)")
    print("   2. Портът е грешен (пробвай с 3306 или 3307)")
    print("   3. Паролата за 'root' не е празна")
    print("   4. Базата 'register_user' не съществува")

except Exception as e:
    print(f"\n❌ ДРУГА ГРЕШКА:")
    print(f"   {type(e).__name__}: {e}")