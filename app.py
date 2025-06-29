import os
import datetime
import google.generativeai as genai
from flask import Flask, request, jsonify
from flask_cors import CORS
from flask_sqlalchemy import SQLAlchemy

# ====================================================================
# 1. Ініціалізація Flask та CORS
# ====================================================================
app = Flask(__name__)
CORS(app)

# ====================================================================
# 2. НОВЕ: Налаштування бази даних
# ====================================================================
# Ми беремо посилання на базу даних з середовища, яке ви налаштували на Render
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# ====================================================================
# 3. НОВЕ: Визначення моделей бази даних
# Щоб цей сервіс знав структуру таблиць, куди він буде писати дані
# ====================================================================
class User(db.Model):
    __tablename__ = 'user' # Явно вказуємо ім'я таблиці
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    # Інші поля нам тут не потрібні, головне - id та username

class ChatLog(db.Model):
    __tablename__ = 'chat_log' # Явно вказуємо ім'я таблиці
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    timestamp = db.Column(db.DateTime, index=True, default=lambda: datetime.datetime.now(datetime.UTC))
    user_prompt = db.Column(db.Text, nullable=False)
    bot_response = db.Column(db.Text, nullable=True)
    user = db.relationship('User', backref=db.backref('chat_logs_backend', lazy='dynamic'))

# ====================================================================
# 4. Налаштування Gemini
# ====================================================================
api_key = os.getenv("GEMINI_API_KEY")

if api_key:
    genai.configure(api_key=api_key)
else:
    print("ПОПЕРЕДЖЕННЯ: Змінна середовища GEMINI_API_KEY не встановлена.")

generation_config = {"temperature": 0.9, "top_p": 1, "top_k": 1, "max_output_tokens": 2048}
model = genai.GenerativeModel(
    model_name="gemini-1.5-flash",
    generation_config=generation_config,
    system_instruction="""Ти — експертний віртуальний консультант для сайту vet25ua.onrender.com.
Твоя спеціалізація — ветеринарія та безпека харчових продуктів. Відповідай виключно на запитання, пов'язані з:
- Ветеринарними препаратами, хворобами тварин.
- Нормами та стандартами харчової промисловості (ДСТУ, ISO, HACCP), а також з можливістю прописувати процедури HACCP.
- Технологіями виробництва та зберігання продуктів в Україні та Євросоюзі.
- Рекомендаціями щодо продажів в Україні та Євросоюзі.
- Клінічними ознаками хворих органів туш тварин, тушок птиці, качок, кролів, індиків, курей.
- Цінами на сільськогосподарську продукцію в Україні та Євросоюзі, аналізом та рекомендаціями для продажу.
- Аналізом хвороб бджіл та їх паразитів, рекомендаціями по лікуванню та усуненню хвороб.
- Способами обробки меду, методами зберігання та стандартами України та Євросоюзу.
- Рекомендаціями щодо кращого продажу меду і супутніх матеріалів (віск, пилок, перга, маточне молочко, тощо).
- Цінами на продукцію бджільництва в Україні та за кордоном.
- Законодавством України, Євросоюзу та інших країн щодо ветеринарії та експертизи м'яса.Закони та інструкції по хворобам сг тварин України.

Якщо запитання не стосується цих тем, ввічливо відмовляй у відповіді, пояснюючи свою спеціалізацію. Наприклад: 'Вибачте, я можу консультувати лише з питань ветеринарії та харчової промисловості'.
"""
)

# ====================================================================
# 5. Маршрути (головний маршрут ЗМІНЕНО)
# ====================================================================
@app.route('/api/chat', methods=['POST'])
def chat():
    if not api_key:
        return jsonify({"error": "API ключ не налаштовано на сервері."}), 500

    # ЗМІНЕНО: Отримуємо не тільки повідомлення, а й ID користувача
    data = request.json
    user_message = data.get("message")
    user_id = data.get("user_id")

    if not all([user_message, user_id]):
        return jsonify({"error": "Повідомлення та ID користувача є обов'язковими"}), 400

    try:
        # Отримуємо відповідь від Gemini
        chat_session = model.start_chat()
        response = chat_session.send_message(user_message)
        bot_response_text = response.text

        # НОВЕ: Зберігаємо лог у базу даних
        try:
            with app.app_context():
                # Перевіряємо, чи існує такий користувач
                user = db.session.get(User, user_id)
                if user:
                    new_log = ChatLog(
                        user_id=user_id,
                        user_prompt=user_message,
                        bot_response=bot_response_text
                    )
                    db.session.add(new_log)
                    db.session.commit()
                else:
                    print(f"ПОПЕРЕДЖЕННЯ: Користувача з ID {user_id} не знайдено. Лог не збережено.")
        except Exception as db_error:
            # Не перериваємо роботу бота, якщо не вдалося зберегти лог
            print(f"ПОМИЛКА збереження логу в БД: {db_error}")

        # Повертаємо відповідь користувачу
        return jsonify({"reply": bot_response_text})

    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/')
def index():
    return "Бекенд чат-бота працює!"

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))