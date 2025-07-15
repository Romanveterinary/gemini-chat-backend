import os
import datetime
import google.generativeai as genai
from flask import Flask, request, jsonify
from flask_cors import CORS
from flask_sqlalchemy import SQLAlchemy
import traceback

# ====================================================================
# 1. Ініціалізація Flask та CORS
# ====================================================================
app = Flask(__name__)
basedir = os.path.abspath(os.path.dirname(__file__))

CORS(app, resources={r"/api/*": {"origins": "*"}})

# ====================================================================
# 2. Налаштування бази даних
# ====================================================================
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# ====================================================================
# 3. Моделі бази даних
# ====================================================================
class User(db.Model):
    __tablename__ = 'user'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)

class ChatLog(db.Model):
    __tablename__ = 'chat_log'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    timestamp = db.Column(db.DateTime, index=True, default=lambda: datetime.datetime.now(datetime.UTC))
    user_prompt = db.Column(db.Text, nullable=False)
    bot_response = db.Column(db.Text, nullable=True)
    retrieved_context = db.Column(db.Text, nullable=True)
    user = db.relationship('User', backref=db.backref('chat_logs_backend', lazy='dynamic'))

# ====================================================================
# 4. Логіка Пошуку по Законах
# ====================================================================
def find_relevant_laws(query):
    legislation_dir = os.path.join(basedir, 'legislation')
    if not os.path.exists(legislation_dir):
        return ""
    
    query_words = set(query.lower().split())
    found_fragments = []

    for filename in os.listdir(legislation_dir):
        if filename.endswith(".txt"):
            try:
                with open(os.path.join(legislation_dir, filename), 'r', encoding='utf-8') as f:
                    content = f.read()
                    paragraphs = content.split('\n\n')
                    for p in paragraphs:
                        if any(word in p.lower() for word in query_words):
                            found_fragments.append(f"З документу '{filename}':\n---\n{p}\n---\n")
            except Exception as e:
                print(f"Помилка читання файлу {filename}: {e}")
    
    return "\n".join(found_fragments)

# ====================================================================
# 5. Налаштування Gemini
# ====================================================================
api_key = os.getenv("GEMINI_API_KEY")

if api_key:
    genai.configure(api_key=api_key)
else:
    print("ПОПЕРЕДЖЕННЯ: Змінна середовища GEMINI_API_KEY не встановлена.")

generation_config = {"temperature": 0.7, "top_p": 1, "top_k": 1, "max_output_tokens": 2048}
model = genai.GenerativeModel(model_name="gemini-1.5-flash", generation_config=generation_config)

# ====================================================================
# 6. Основний маршрут чату (Синхронна версія)
# ====================================================================
@app.route('/api/chat', methods=['POST'])
def chat():
    if not api_key:
        return jsonify({"error": "API ключ не налаштовано на сервері."}), 500

    data = request.json
    user_message = data.get("message")
    user_id = data.get("user_id")

    if not all([user_message, user_id]):
        return jsonify({"error": "Повідомлення та ID користувача є обов'язковими"}), 400

    try:
        retrieved_context = find_relevant_laws(user_message)

        # Створюємо чат-сесію з динамічним системним промптом
        system_instruction = f"""Ти — експертний віртуальний консультант для сайту vet25ua.onrender.com. Твоя спеціалізація — ветеринарія та законодавство України.
Відповідай на запитання користувача, базуючись в першу чергу на НАДАНОМУ КОНТЕКСТІ. Якщо контекст релевантний, посилайся на нього.
Якщо запитання не стосується ветеринарії, харчової промисловості або законодавства у цих сферах, ввічливо відмов.

**НАДАНИЙ КОНТЕКСТ ІЗ ЗАКОНОДАВСТВА:**
{retrieved_context if retrieved_context else "Для цього запиту релевантних документів у локальній базі знань не знайдено."}
"""
        
        chat_session = model.start_chat(history=[
            {'role': 'user', 'parts': [system_instruction]},
            {'role': 'model', 'parts': ["Так, я готовий допомогти."]}
        ])
        
        response = chat_session.send_message(user_message)
        bot_response_text = response.text

        try:
            with app.app_context():
                user = db.session.get(User, user_id)
                if user:
                    new_log = ChatLog(
                        user_id=user_id,
                        user_prompt=user_message,
                        bot_response=bot_response_text,
                        retrieved_context=retrieved_context
                    )
                    db.session.add(new_log)
                    db.session.commit()
        except Exception as db_error:
            print(f"ПОМИЛКА збереження логу в БД: {db_error}")
            traceback.print_exc()

        return jsonify({"reply": bot_response_text})

    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500

@app.route('/')
def index():
    return "Бекенд чат-бота працює!"

# ====================================================================
# 7. Запуск додатку
# ====================================================================
if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))