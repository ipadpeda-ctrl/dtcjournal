import os
from flask import Flask, render_template, redirect, url_for, request, flash
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from flask_bcrypt import Bcrypt
from datetime import datetime
import json
import statistics 

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
    
    # NUOVI CAMPI: Impostazioni personali per le conferme (Salviamo come stringa separata da virgola)
    pros_settings = db.Column(db.Text, default="Trendline,Supporto,Rottura Struttura") 
    cons_settings = db.Column(db.Text, default="Contro Trend,News in arrivo")

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
    
    outcome = db.Column(db.String(20)) # Target, Stop Loss, Breakeven, Non Fillato, Setup
    result_percent = db.Column(db.Float) 
    
    # Ora timeframe salverà valori multipli (es: "m15,m5")
    timeframe = db.Column(db.String(50)) 
    
    # NUOVI CAMPI: Conferme selezionate per questo trade
    selected_pros = db.Column(db.Text) # Es: "Trendline,Supporto"
    selected_cons = db.Column(db.Text)
    
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

        if User.query.first() is None:
            role = 'admin'
        else:
            role = 'student'

        hashed_password = bcrypt.generate_password_hash(password).decode('utf-8')
        new_user = User(username=username, password=hashed_password, role=role)
        db.session.add(new_user)
        db.session.commit()
        
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
            flash('Login fallito.', 'danger')
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

# --- NUOVA ROTTA IMPOSTAZIONI ---
@app.route('/settings', methods=['GET', 'POST'])
@login_required
def settings():
    if request.method == 'POST':
        # Prende le liste dal form, le pulisce e le salva come stringa
        pros = request.form.getlist('pros_item')
        cons = request.form.getlist('cons_item')
        
        # Filtra stringhe vuote e unisce con virgola
        current_user.pros_settings = ",".join([p.strip() for p in pros if p.strip()])
        current_user.cons_settings = ",".join([c.strip() for c in cons if c.strip()])
        
        db.session.commit()
        flash('Impostazioni conferme aggiornate!', 'success')
        return redirect(url_for('dashboard'))
        
    # Prepara le liste per mostrarle negli input
    user_pros = current_user.pros_settings.split(',') if current_user.pros_settings else []
    user_cons = current_user.cons_settings.split(',') if current_user.cons_settings else []
    
    # Riempiamo fino a 7 slot vuoti per il frontend
    while len(user_pros) < 7: user_pros.append("")
    while len(user_cons) < 7: user_cons.append("")
    
    return render_template('settings.html', user_pros=user_pros, user_cons=user_cons)

@app.route('/dashboard')
@login_required
def dashboard():
    if current_user.role == 'admin':
        entries = JournalEntry.query.order_by(JournalEntry.date.desc()).all()
        admin_view = True
    else:
        entries = JournalEntry.query.filter_by(user_id=current_user.id).order_by(JournalEntry.date.desc()).all()
        admin_view = False
    
    # Carichiamo le impostazioni dell'utente per il form di inserimento
    user_pros = [p for p in (current_user.pros_settings.split(',') if current_user.pros_settings else []) if p]
    user_cons = [c for c in (current_user.cons_settings.split(',') if current_user.cons_settings else []) if c]

    return render_template('dashboard.html', entries=entries, admin_view=admin_view, user=current_user, user_pros=user_pros, user_cons=user_cons)

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

    # Filtriamo i trade validi per le statistiche (escludiamo Setup e Non Fillato dal Win Rate)
    active_trades = [t for t in trades if t.outcome in ['Target', 'Stop Loss', 'Breakeven']]
    
    # 1. Statistiche Generali
    wins = [t.result_percent for t in active_trades if t.outcome == 'Target']
    losses = [t.result_percent for t in active_trades if t.outcome == 'Stop Loss']
    
    total_active = len(active_trades)
    num_wins = len(wins)
    num_losses = len(losses)
    num_be = len([t for t in active_trades if t.outcome == 'Breakeven'])
    
    # Conteggi Extra
    num_non_fill = len([t for t in trades if t.outcome == 'Non Fillato'])
    num_setup = len([t for t in trades if t.outcome == 'Setup'])

    win_rate = round((num_wins / total_active * 100), 2) if total_active > 0 else 0
    
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    net_result = round(gross_profit - gross_loss, 2)
    profit_factor = round(gross_profit / gross_loss, 2) if gross_loss > 0 else round(gross_profit, 2)

    avg_win = round(statistics.mean(wins), 2) if wins else 0
    avg_loss = round(statistics.mean(losses), 2) if losses else 0
    expectancy = 0
    if total_active > 0:
        win_rate_dec = num_wins / total_active
        loss_rate_dec = num_losses / total_active
        expectancy = round((win_rate_dec * avg_win) - (loss_rate_dec * abs(avg_loss)), 2)

    # 2. STATISTICHE TIMEFRAME (Distribuzione)
    tf_stats = {} # Struttura: {'m15': {'total': 0, 'wins': 0, 'result': 0}}
    
    for t in active_trades:
        if t.timeframe:
            # Splitta i TF se sono multipli (es. "m15,m5")
            tfs = t.timeframe.split(',')
            for tf in tfs:
                tf = tf.strip()
                if tf not in tf_stats:
                    tf_stats[tf] = {'total': 0, 'wins': 0, 'result': 0.0}
                
                tf_stats[tf]['total'] += 1
                tf_stats[tf]['result'] += t.result_percent
                if t.outcome == 'Target':
                    tf_stats[tf]['wins'] += 1

    # Formattazione per la tabella
    tf_table_data = []
    for tf, data in tf_stats.items():
        wr = round((data['wins'] / data['total'] * 100), 1) if data['total'] > 0 else 0
        tf_table_data.append({
            'name': tf,
            'total': data['total'],
            'win_rate': wr,
            'result': round(data['result'], 2)
        })
    # Ordina per numero di trade
    tf_table_data.sort(key=lambda x: x['total'], reverse=True)

    # 3. Grafici (Equity e Orario) - come prima
    hourly_stats = {h: {'wins': 0, 'total': 0} for h in range(24)}
    for t in active_trades:
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
            hourly_data.append(round((hourly_stats[h]['wins'] / hourly_stats[h]['total']) * 100, 1))

    chart_labels = []
    chart_data = []
    running_total = 0
    # Equity curve include tutti i trade che hanno generato profitti/perdite (anche se non attivi per statistica winrate, ma qui usiamo active_trades per coerenza)
    # Ordiniamo per data ASC per il grafico
    chronological_trades = sorted(active_trades, key=lambda x: x.date)
    for t in chronological_trades:
        running_total += t.result_percent
        chart_labels.append(t.date.strftime('%d/%m'))
        chart_data.append(round(running_total, 2))

    return render_template('statistics.html', 
                           no_data=False,
                           user=current_user,
                           admin_view=admin_view,
                           # KPI
                           win_rate=win_rate,
                           profit_factor=profit_factor,
                           net_result=net_result,
                           expectancy=expectancy,
                           total_trades=len(trades), # Totale incluso setup/non fillati
                           total_active=total_active, # Totale validi per stats
                           num_wins=num_wins,
                           num_losses=num_losses,
                           num_be=num_be,
                           num_non_fill=num_non_fill,
                           num_setup=num_setup,
                           # Tables & Charts
                           tf_table_data=tf_table_data,
                           chart_labels=json.dumps(chart_labels),
                           chart_data=json.dumps(chart_data),
                           hourly_labels=json.dumps(hourly_labels),
                           hourly_data=json.dumps(hourly_data))

@app.route('/add_trade', methods=['POST'])
@login_required
def add_trade():
    try:
        # Gestione Multi-selezione (Liste)
        timeframes = request.form.getlist('timeframe') # Ritorna lista es. ['m15', 'm5']
        selected_pros = request.form.getlist('pros')
        selected_cons = request.form.getlist('cons')
        
        # Unione Link
        link1 = request.form.get('link1', '').strip()
        link2 = request.form.get('link2', '').strip()
        screen_combined = ",".join([l for l in [link1, link2] if l])

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
            
            # Salvataggio liste come stringhe
            timeframe=",".join(timeframes),
            selected_pros=",".join(selected_pros),
            selected_cons=",".join(selected_cons),
            
            screen_pre=screen_combined,
            emotions=request.form.get('emotions'),
            notes=request.form.get('notes')
        )
        db.session.add(new_entry)
        db.session.commit()
        flash('Trade aggiunto!', 'success')
    except Exception as e:
        flash(f'Errore: {str(e)}', 'danger')
        
    return redirect(url_for('dashboard'))

@app.route('/delete_trade/<int:id>')
@login_required
def delete_trade(id):
    trade = JournalEntry.query.get_or_404(id)
    if trade.user_id != current_user.id and current_user.role != 'admin':
        flash('Non autorizzato', 'danger')
        return redirect(url_for('dashboard'))
    db.session.delete(trade)
    db.session.commit()
    flash('Eliminato.', 'success')
    return redirect(url_for('dashboard'))

@app.route('/edit_trade/<int:id>', methods=['GET', 'POST'])
@login_required
def edit_trade(id):
    trade = JournalEntry.query.get_or_404(id)
    if trade.user_id != current_user.id and current_user.role != 'admin':
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
        trade.emotions = request.form.get('emotions')
        trade.notes = request.form.get('notes')
        
        # Aggiornamento liste
        trade.timeframe = ",".join(request.form.getlist('timeframe'))
        trade.selected_pros = ",".join(request.form.getlist('pros'))
        trade.selected_cons = ",".join(request.form.getlist('cons'))
        
        # Link
        link1 = request.form.get('link1', '').strip()
        link2 = request.form.get('link2', '').strip()
        trade.screen_pre = ",".join([l for l in [link1, link2] if l])

        db.session.commit()
        flash('Modificato!', 'success')
        return redirect(url_for('dashboard'))
    
    # Preparazione dati per la vista
    curr_tfs = trade.timeframe.split(',') if trade.timeframe else []
    curr_pros = trade.selected_pros.split(',') if trade.selected_pros else []
    curr_cons = trade.selected_cons.split(',') if trade.selected_cons else []
    current_links = trade.screen_pre.split(',') if trade.screen_pre else []
    
    # Carichiamo le impostazioni utente per generare le checkbox
    user_pros_list = [p for p in (current_user.pros_settings.split(',') if current_user.pros_settings else []) if p]
    user_cons_list = [c for c in (current_user.cons_settings.split(',') if current_user.cons_settings else []) if c]

    return render_template('edit_trade.html', trade=trade, 
                           curr_tfs=curr_tfs, curr_pros=curr_pros, curr_cons=curr_cons,
                           user_pros_list=user_pros_list, user_cons_list=user_cons_list,
                           val_link1=current_links[0] if len(current_links)>0 else '',
                           val_link2=current_links[1] if len(current_links)>1 else '')

with app.app_context():
    db.create_all()

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5001))
    app.run(host="0.0.0.0", port=port)