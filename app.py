import os
from flask import Flask, render_template, redirect, url_for, request, flash
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from flask_bcrypt import Bcrypt
from datetime import datetime
import json
import statistics 

# --- CONFIGURAZIONE APP ---
app = Flask(__name__)

# Configurazione Sicurezza e Database
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'chiave-segreta-sviluppo-locale')

database_url = os.environ.get('DATABASE_URL')
if database_url and database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql://", 1)

app.config['SQLALCHEMY_DATABASE_URI'] = database_url or 'sqlite:///trading_journal.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
bcrypt = Bcrypt(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

# --- MODELLI DEL DATABASE ---

class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(150), unique=True, nullable=False)
    password = db.Column(db.String(150), nullable=False)
    role = db.Column(db.String(20), default='student') 
    trades = db.relationship('JournalEntry', backref='author', lazy=True)

class JournalEntry(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    
    pair = db.Column(db.String(10), nullable=False)
    date = db.Column(db.Date, nullable=False, default=datetime.utcnow)
    time = db.Column(db.String(10)) 
    direction = db.Column(db.String(10)) 
    
    risk_percent = db.Column(db.Float)
    rr_final = db.Column(db.Float)
    pips_tp = db.Column(db.Float)
    pips_sl = db.Column(db.Float)
    
    outcome = db.Column(db.String(20)) 
    result_percent = db.Column(db.Float) 
    
    timeframe = db.Column(db.String(10)) 
    setup = db.Column(db.String(50))
    sentiment = db.Column(db.String(50))
    
    screen_pre = db.Column(db.Text) 
    screen_post = db.Column(db.String(200)) 
    notes = db.Column(db.Text)
    emotions = db.Column(db.String(50))

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# --- ROUTES ---

@app.route('/')
def home():
    return redirect(url_for('login'))

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        existing_user = User.query.filter_by(username=username).first()
        if existing_user:
            flash('Nome utente già in uso.', 'danger')
            return redirect(url_for('register'))

        # LOGICA AUTOMATICA ADMIN: Se è il primo utente del DB, diventa Admin
        if User.query.first() is None:
            role = 'admin'
        else:
            role = 'student'

        hashed_password = bcrypt.generate_password_hash(password).decode('utf-8')
        new_user = User(username=username, password=hashed_password, role=role)
        db.session.add(new_user)
        db.session.commit()
        
        if role == 'admin':
            flash('Account creato! Sei il primo utente: ADMIN MODE ATTIVO.', 'success')
        else:
            flash('Account creato! Ora puoi accedere.', 'success')
            
        return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        user = User.query.filter_by(username=username).first()
        if user and bcrypt.check_password_hash(user.password, password):
            login_user(user)
            return redirect(url_for('dashboard'))
        else:
            flash('Login fallito. Controlla i dati.', 'danger')
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

@app.route('/dashboard')
@login_required
def dashboard():
    if current_user.role == 'admin':
        entries = JournalEntry.query.order_by(JournalEntry.date.desc()).all()
        admin_view = True
    else:
        entries = JournalEntry.query.filter_by(user_id=current_user.id).order_by(JournalEntry.date.desc()).all()
        admin_view = False
        
    return render_template('dashboard.html', entries=entries, admin_view=admin_view, user=current_user)

@app.route('/statistics')
@login_required
def statistics_page():
    if current_user.role == 'admin':
        trades = JournalEntry.query.order_by(JournalEntry.date.asc()).all()
        admin_view = True
    else:
        trades = JournalEntry.query.filter_by(user_id=current_user.id).order_by(JournalEntry.date.asc()).all()
        admin_view = False

    if not trades:
        return render_template('statistics.html', no_data=True, user=current_user)

    total_trades = len(trades)
    wins = [t.result_percent for t in trades if t.outcome == 'Target']
    losses = [t.result_percent for t in trades if t.outcome == 'Stop Loss']
    breakevens = [t for t in trades if t.outcome == 'Breakeven']
    
    num_wins = len(wins)
    num_losses = len(losses)
    num_be = len(breakevens)

    win_rate = round((num_wins / total_trades * 100), 2)
    
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    net_result = round(gross_profit - gross_loss, 2)
    
    profit_factor = round(gross_profit / gross_loss, 2) if gross_loss > 0 else round(gross_profit, 2)

    avg_win = round(statistics.mean(wins), 2) if wins else 0
    avg_loss = round(statistics.mean(losses), 2) if losses else 0
    rr_realized = round(avg_win / abs(avg_loss), 2) if avg_loss != 0 else 0

    win_rate_dec = num_wins / total_trades
    loss_rate_dec = num_losses / total_trades
    expectancy = round((win_rate_dec * avg_win) - (loss_rate_dec * abs(avg_loss)), 2)

    longs = [t for t in trades if t.direction == 'Long']
    shorts = [t for t in trades if t.direction == 'Short']
    long_wins = len([t for t in longs if t.outcome == 'Target'])
    short_wins = len([t for t in shorts if t.outcome == 'Target'])
    long_wr = round((long_wins/len(longs)*100), 2) if longs else 0
    short_wr = round((short_wins/len(shorts)*100), 2) if shorts else 0

    hourly_stats = {h: {'wins': 0, 'total': 0} for h in range(24)}
    for t in trades:
        if t.time:
            try:
                hour = int(t.time.split(':')[0])
                hourly_stats[hour]['total'] += 1
                if t.outcome == 'Target':
                    hourly_stats[hour]['wins'] += 1
            except: pass

    hourly_labels = []
    hourly_data = []
    for h in range(24):
        if hourly_stats[h]['total'] > 0:
            hourly_labels.append(f"{h:02d}:00")
            win_pct = round((hourly_stats[h]['wins'] / hourly_stats[h]['total']) * 100, 1)
            hourly_data.append(win_pct)

    chart_labels = []
    chart_data = []
    running_total = 0
    for t in trades:
        running_total += t.result_percent
        chart_labels.append(t.date.strftime('%d/%m'))
        chart_data.append(round(running_total, 2))

    return render_template('statistics.html', 
                           no_data=False,
                           user=current_user,
                           admin_view=admin_view,
                           total_trades=total_trades,
                           win_rate=win_rate,
                           profit_factor=profit_factor,
                           net_result=net_result,
                           avg_win=avg_win,
                           avg_loss=avg_loss,
                           rr_realized=rr_realized,
                           expectancy=expectancy,
                           num_wins=num_wins,
                           num_losses=num_losses,
                           num_be=num_be,
                           long_count=len(longs),
                           short_count=len(shorts),
                           long_wr=long_wr,
                           short_wr=short_wr,
                           chart_labels=json.dumps(chart_labels),
                           chart_data=json.dumps(chart_data),
                           hourly_labels=json.dumps(hourly_labels),
                           hourly_data=json.dumps(hourly_data))

@app.route('/add_trade', methods=['POST'])
@login_required
def add_trade():
    try:
        link1 = request.form.get('link1', '').strip()
        link2 = request.form.get('link2', '').strip()
        links_list = [l for l in [link1, link2] if l]
        screen_combined = ",".join(links_list)

        new_entry = JournalEntry(
            user_id=current_user.id,
            pair=request.form.get('pair'),
            date=datetime.strptime(request.form.get('date'), '%Y-%m-%d'),
            time=request.form.get('time'),
            direction=request.form.get('direction'),
            risk_percent=float(request.form.get('risk_percent') or 0),
            rr_final=float(request.form.get('rr_final') or 0),
            outcome=request.form.get('outcome'),
            result_percent=float(request.form.get('result_percent') or 0),
            timeframe=request.form.get('timeframe'),
            screen_pre=screen_combined,
            emotions=request.form.get('emotions'),
            notes=request.form.get('notes')
        )
        db.session.add(new_entry)
        db.session.commit()
        flash('Trade aggiunto correttamente!', 'success')
    except Exception as e:
        flash(f'Errore inserimento: {str(e)}', 'danger')
        
    return redirect(url_for('dashboard'))

@app.route('/delete_trade/<int:id>')
@login_required
def delete_trade(id):
    trade = JournalEntry.query.get_or_404(id)
    if trade.user_id != current_user.id and current_user.role != 'admin':
        flash('Azione non autorizzata', 'danger')
        return redirect(url_for('dashboard'))
    
    db.session.delete(trade)
    db.session.commit()
    flash('Trade eliminato.', 'success')
    return redirect(url_for('dashboard'))

@app.route('/edit_trade/<int:id>', methods=['GET', 'POST'])
@login_required
def edit_trade(id):
    trade = JournalEntry.query.get_or_404(id)
    if trade.user_id != current_user.id and current_user.role != 'admin':
        flash('Azione non autorizzata', 'danger')
        return redirect(url_for('dashboard'))
    
    if request.method == 'POST':
        trade.pair = request.form.get('pair')
        trade.date = datetime.strptime(request.form.get('date'), '%Y-%m-%d')
        trade.time = request.form.get('time')
        trade.direction = request.form.get('direction')
        trade.outcome = request.form.get('outcome')
        trade.risk_percent = float(request.form.get('risk_percent') or 0)
        trade.result_percent = float(request.form.get('result_percent') or 0)
        trade.rr_final = float(request.form.get('rr_final') or 0)
        trade.timeframe = request.form.get('timeframe')
        trade.emotions = request.form.get('emotions')
        trade.notes = request.form.get('notes')
        
        link1 = request.form.get('link1', '').strip()
        link2 = request.form.get('link2', '').strip()
        links_list = [l for l in [link1, link2] if l]
        trade.screen_pre = ",".join(links_list)

        db.session.commit()
        flash('Modifiche salvate!', 'success')
        return redirect(url_for('dashboard'))
    
    current_links = trade.screen_pre.split(',') if trade.screen_pre else []
    val_link1 = current_links[0] if len(current_links) > 0 else ''
    val_link2 = current_links[1] if len(current_links) > 1 else ''

    return render_template('edit_trade.html', trade=trade, val_link1=val_link1, val_link2=val_link2)

# --- AVVIO E CREAZIONE DB ---
# Questo blocco assicura che le tabelle vengano create anche su Render
with app.app_context():
    db.create_all()

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5001))
    app.run(host="0.0.0.0", port=port)