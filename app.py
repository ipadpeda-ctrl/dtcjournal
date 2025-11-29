import os
from flask import Flask, render_template, redirect, url_for, request, flash
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from flask_bcrypt import Bcrypt
from datetime import datetime
from sqlalchemy import func
import json
import statistics 

app = Flask(__name__)

# --- ANTI-CACHE ---
app.config['TEMPLATES_AUTO_RELOAD'] = True
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0

@app.after_request
def add_header(response):
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, post-check=0, pre-check=0, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '-1'
    return response

# --- CONFIG ---
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'chiave-segreta-sviluppo-locale')
ADMIN_USER = "matte" 

database_url = os.environ.get('DATABASE_URL')
if database_url and database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql://", 1)

app.config['SQLALCHEMY_DATABASE_URI'] = database_url or 'sqlite:///trading_journal.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
bcrypt = Bcrypt(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

# --- MODELS ---
class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(150), unique=True, nullable=False)
    password = db.Column(db.String(150), nullable=False)
    role = db.Column(db.String(20), default='student') 
    trades = db.relationship('JournalEntry', backref='author', lazy=True)
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
    outcome = db.Column(db.String(20)) 
    result_percent = db.Column(db.Float) 
    timeframe = db.Column(db.String(50)) 
    selected_pros = db.Column(db.Text) 
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
def home(): return redirect(url_for('login'))

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        if User.query.filter_by(username=username).first():
            flash('Utente già esistente.', 'danger')
            return redirect(url_for('register'))
        role = 'admin' if username == ADMIN_USER else 'student'
        new_user = User(username=username, password=bcrypt.generate_password_hash(password).decode('utf-8'), role=role)
        db.session.add(new_user)
        db.session.commit()
        return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user = User.query.filter_by(username=request.form.get('username')).first()
        if user and bcrypt.check_password_hash(user.password, request.form.get('password')):
            login_user(user)
            return redirect(url_for('dashboard'))
        flash('Login fallito.', 'danger')
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

@app.route('/settings', methods=['GET', 'POST'])
@login_required
def settings():
    if request.method == 'POST':
        current_user.pros_settings = ",".join([p.strip() for p in request.form.getlist('pros_item') if p.strip()])
        current_user.cons_settings = ",".join([c.strip() for c in request.form.getlist('cons_item') if c.strip()])
        db.session.commit()
        flash('Impostazioni salvate!', 'success')
        return redirect(url_for('dashboard'))
    u_pros = current_user.pros_settings.split(',') if current_user.pros_settings else []
    u_cons = current_user.cons_settings.split(',') if current_user.cons_settings else []
    while len(u_pros) < 7: u_pros.append("")
    while len(u_cons) < 7: u_cons.append("")
    return render_template('settings.html', user_pros=u_pros, user_cons=u_cons)

@app.route('/dashboard')
@login_required
def dashboard():
    pair_filter = request.args.get('pair_filter')
    outcome_filter = request.args.get('outcome_filter')
    date_filter = request.args.get('date_filter')

    query = JournalEntry.query
    if current_user.role != 'admin':
        query = query.filter_by(user_id=current_user.id)
    
    if pair_filter: query = query.filter(JournalEntry.pair == pair_filter)
    if outcome_filter: query = query.filter(JournalEntry.outcome == outcome_filter)
    if date_filter:
        year, month = date_filter.split('-')
        query = query.filter(db.extract('year', JournalEntry.date) == int(year))
        query = query.filter(db.extract('month', JournalEntry.date) == int(month))

    page = request.args.get('page', 1, type=int)
    pagination = query.order_by(JournalEntry.date.desc()).paginate(page=page, per_page=15, error_out=False)
    
    u_pros = [p for p in (current_user.pros_settings.split(',') if current_user.pros_settings else []) if p]
    u_cons = [c for c in (current_user.cons_settings.split(',') if current_user.cons_settings else []) if c]

    return render_template('dashboard.html', pagination=pagination, admin_view=(current_user.role == 'admin'), user=current_user, user_pros=u_pros, user_cons=u_cons)

@app.route('/statistics')
@login_required
def statistics_page():
    admin_view = (current_user.role == 'admin')
    base_query = JournalEntry.query
    if not admin_view:
        base_query = base_query.filter_by(user_id=current_user.id)
    
    trades = base_query.order_by(JournalEntry.date.asc()).all()
    if not trades: return render_template('statistics.html', no_data=True, user=current_user, admin_view=admin_view)

    # 1. KPI BASE
    active_trades = [t for t in trades if t.outcome in ['Target', 'Stop Loss', 'Breakeven']]
    wins = [t.result_percent for t in active_trades if t.outcome == 'Target']
    losses = [t.result_percent for t in active_trades if t.outcome == 'Stop Loss']
    
    total_active = len(active_trades)
    num_wins = len(wins)
    num_losses = len(losses)
    num_be = len([t for t in active_trades if t.outcome == 'Breakeven'])
    
    num_non_fill = len([t for t in trades if t.outcome == 'Non Fillato'])
    num_setup = len([t for t in trades if t.outcome == 'Setup'])

    win_rate = round((num_wins / total_active * 100), 2) if total_active > 0 else 0
    profit_factor = round(sum(wins) / abs(sum(losses)), 2) if losses else round(sum(wins), 2)
    net_result = round(sum(wins) - abs(sum(losses)), 2)
    expectancy = round(((num_wins/total_active) * (statistics.mean(wins) if wins else 0)) - ((num_losses/total_active) * (statistics.mean(losses) if losses else 0)), 2) if total_active > 0 else 0

    # 2. ANALISI CONFLUENZE (Tabella Automatica Pro/Contro)
    tag_stats = {} # { 'Trendline': {'total':10, 'wins':5, 'loss':3, 'be':2}, ... }
    
    for t in active_trades:
        # Uniamo liste pro e contro in un unico calderone di tag da analizzare
        tags = []
        if t.selected_pros: tags.extend([p.strip() for p in t.selected_pros.split(',') if p.strip()])
        if t.selected_cons: tags.extend([c.strip() for c in t.selected_cons.split(',') if c.strip()])
        
        for tag in tags:
            if tag not in tag_stats: tag_stats[tag] = {'total':0, 'wins':0, 'loss':0, 'be':0}
            tag_stats[tag]['total'] += 1
            if t.outcome == 'Target': tag_stats[tag]['wins'] += 1
            elif t.outcome == 'Stop Loss': tag_stats[tag]['loss'] += 1
            elif t.outcome == 'Breakeven': tag_stats[tag]['be'] += 1

    # Formattazione lista ordinata per Totale Apparizioni
    confluence_table = []
    for tag, data in tag_stats.items():
        wr = round(data['wins']/data['total']*100, 1) if data['total']>0 else 0
        confluence_table.append({'name': tag, 'total': data['total'], 'wins': data['wins'], 'loss': data['loss'], 'be': data['be'], 'win_rate': wr})
    confluence_table.sort(key=lambda x: x['total'], reverse=True)

    # 3. GRAFICO ORARIO STACKED (Distribuzione Esiti per Ora)
    # Struttura: { 0: {'Target':0, 'Stop Loss':0, 'Breakeven':0}, 1: ... }
    hourly_dist = {h: {'Target': 0, 'Stop Loss': 0, 'Breakeven': 0} for h in range(24)}
    
    for t in active_trades:
        if t.time:
            try:
                h = int(t.time.split(':')[0])
                if t.outcome in ['Target', 'Stop Loss', 'Breakeven']:
                    hourly_dist[h][t.outcome] += 1
            except: pass

    # Preparazione Array per Chart.js
    hours_labels = [f"{h:02d}:00" for h in range(24)]
    data_target = [hourly_dist[h]['Target'] for h in range(24)]
    data_stop = [hourly_dist[h]['Stop Loss'] for h in range(24)]
    data_be = [hourly_dist[h]['Breakeven'] for h in range(24)]

    # 4. ALTRE TABELLE
    tf_stats = {}
    for t in active_trades:
        if t.timeframe:
            for tf in t.timeframe.split(','):
                tf = tf.strip()
                if tf not in tf_stats: tf_stats[tf] = {'total': 0, 'wins': 0, 'result': 0.0}
                tf_stats[tf]['total'] += 1
                tf_stats[tf]['result'] += t.result_percent
                if t.outcome == 'Target': tf_stats[tf]['wins'] += 1
    
    tf_table = []
    for tf, data in tf_stats.items():
        tf_table.append({'name': tf, 'total': data['total'], 'win_rate': round(data['wins']/data['total']*100,1) if data['total'] else 0, 'result': round(data['result'], 2)})
    tf_table.sort(key=lambda x: x['total'], reverse=True)

    # Grafico Equity
    chart_labels, chart_data = [], []
    run_tot = 0
    for t in sorted(active_trades, key=lambda x: x.date):
        run_tot += t.result_percent
        chart_labels.append(t.date.strftime('%d/%m'))
        chart_data.append(round(run_tot, 2))

    return render_template('statistics.html', no_data=False, user=current_user, admin_view=admin_view,
                           win_rate=win_rate, profit_factor=profit_factor, net_result=net_result, expectancy=expectancy,
                           num_non_fill=num_non_fill, num_setup=num_setup, tf_table=tf_table, confluence_table=confluence_table,
                           chart_labels=json.dumps(chart_labels), chart_data=json.dumps(chart_data),
                           hours_labels=json.dumps(hours_labels), 
                           data_target=json.dumps(data_target), data_stop=json.dumps(data_stop), data_be=json.dumps(data_be))

@app.route('/add_trade', methods=['POST'])
@login_required
def add_trade():
    try:
        sc = ",".join([l for l in [request.form.get('link1','').strip(), request.form.get('link2','').strip()] if l])
        new_entry = JournalEntry(
            user_id=current_user.id, pair=request.form.get('pair'), date=datetime.strptime(request.form.get('date'), '%Y-%m-%d'),
            time=request.form.get('time'), direction=request.form.get('direction'),
            risk_percent=float(request.form.get('risk_percent') or 0), rr_final=float(request.form.get('rr_final') or 0),
            outcome=request.form.get('outcome'), result_percent=float(request.form.get('result_percent') or 0),
            timeframe=",".join(request.form.getlist('timeframe')), selected_pros=",".join(request.form.getlist('pros')),
            selected_cons=",".join(request.form.getlist('cons')), screen_pre=sc, emotions=request.form.get('emotions'), notes=request.form.get('notes')
        )
        db.session.add(new_entry)
        db.session.commit()
        flash('Trade aggiunto!', 'success')
    except Exception as e: flash(f'Errore: {str(e)}', 'danger')
    return redirect(url_for('dashboard'))

@app.route('/delete_trade/<int:id>')
@login_required
def delete_trade(id):
    trade = JournalEntry.query.get_or_404(id)
    if trade.user_id == current_user.id or current_user.role == 'admin':
        db.session.delete(trade)
        db.session.commit()
    return redirect(url_for('dashboard'))

@app.route('/edit_trade/<int:id>', methods=['GET', 'POST'])
@login_required
def edit_trade(id):
    trade = JournalEntry.query.get_or_404(id)
    if trade.user_id != current_user.id and current_user.role != 'admin': return redirect(url_for('dashboard'))
    
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
        trade.timeframe = ",".join(request.form.getlist('timeframe'))
        trade.selected_pros = ",".join(request.form.getlist('pros'))
        trade.selected_cons = ",".join(request.form.getlist('cons'))
        trade.screen_pre = ",".join([l for l in [request.form.get('link1','').strip(), request.form.get('link2','').strip()] if l])
        db.session.commit()
        flash('Modificato!', 'success')
        return redirect(url_for('dashboard'))
    
    curr_tfs = trade.timeframe.split(',') if trade.timeframe else []
    curr_pros = trade.selected_pros.split(',') if trade.selected_pros else []
    curr_cons = trade.selected_cons.split(',') if trade.selected_cons else []
    cur_lnks = trade.screen_pre.split(',') if trade.screen_pre else []
    u_pros = [p for p in (current_user.pros_settings.split(',') if current_user.pros_settings else []) if p]
    u_cons = [c for c in (current_user.cons_settings.split(',') if current_user.cons_settings else []) if c]

    return render_template('edit_trade.html', trade=trade, curr_tfs=curr_tfs, curr_pros=curr_pros, curr_cons=curr_cons, user_pros_list=u_pros, user_cons_list=u_cons, val_link1=cur_lnks[0] if len(cur_lnks)>0 else '', val_link2=cur_lnks[1] if len(cur_lnks)>1 else '')

with app.app_context(): db.create_all()
if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5001))

    app.run(host="0.0.0.0", port=port)
