import os
from flask import Flask, render_template, redirect, url_for, request, flash
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from flask_bcrypt import Bcrypt
from datetime import datetime
from sqlalchemy import func, extract
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
    # FILTRI DASHBOARD
    pair_filter = request.args.get('pair_filter')
    outcome_filter = request.args.get('outcome_filter')
    date_filter = request.args.get('date_filter') # Mese corrente: "2023-11"

    query = JournalEntry.query
    if current_user.role != 'admin':
        query = query.filter_by(user_id=current_user.id)
    
    # Applicazione Filtri
    if pair_filter:
        query = query.filter(JournalEntry.pair == pair_filter)
    if outcome_filter:
        query = query.filter(JournalEntry.outcome == outcome_filter)
    if date_filter:
        # Filtro per mese/anno (Formato YYYY-MM)
        year, month = date_filter.split('-')
        # Nota: estrazione generica per compatibilità SQL
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
    
    win_rate = round((num_wins / total_active * 100), 2) if total_active > 0 else 0
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    net_result = round(gross_profit - gross_loss, 2)
    profit_factor = round(gross_profit / gross_loss, 2) if gross_loss > 0 else round(gross_profit, 2)
    expectancy = round(((num_wins/total_active) * (statistics.mean(wins) if wins else 0)) - ((num_losses/total_active) * (statistics.mean(losses) if losses else 0)), 2) if total_active > 0 else 0

    # 2. ANALISI ASSET (Nuova)
    asset_stats = {}
    for t in active_trades:
        if t.pair not in asset_stats: asset_stats[t.pair] = {'total': 0, 'wins': 0, 'result': 0.0}
        asset_stats[t.pair]['total'] += 1
        asset_stats[t.pair]['result'] += t.result_percent
        if t.outcome == 'Target': asset_stats[t.pair]['wins'] += 1
    
    asset_table = []
    for pair, data in asset_stats.items():
        asset_table.append({'name': pair, 'total': data['total'], 'win_rate': round(data['wins']/data['total']*100, 1), 'result': round(data['result'], 2)})
    asset_table.sort(key=lambda x: x['result'], reverse=True) # Ordinati per profitto

    # 3. ANALISI GIORNO SETTIMANA (Nuova)
    # 0=Mon, 6=Sun
    day_map = {0: 'Lun', 1: 'Mar', 2: 'Mer', 3: 'Gio', 4: 'Ven', 5: 'Sab', 6: 'Dom'}
    day_stats = {d: {'wins': 0, 'total': 0} for d in day_map.values()}
    
    for t in active_trades:
        day_name = day_map[t.date.weekday()]
        day_stats[day_name]['total'] += 1
        if t.outcome == 'Target': day_stats[day_name]['wins'] += 1
        
    day_labels = list(day_map.values())
    day_data = []
    for day in day_labels:
        data = day_stats[day]
        wr = round((data['wins'] / data['total'] * 100), 1) if data['total'] > 0 else 0
        day_data.append(wr)

    # 4. LONG vs SHORT (Nuova)
    ls_stats = {'Long': {'total':0, 'wins':0, 'res':0}, 'Short': {'total':0, 'wins':0, 'res':0}}
    for t in active_trades:
        if t.direction in ls_stats:
            ls_stats[t.direction]['total'] += 1
            ls_stats[t.direction]['res'] += t.result_percent
            if t.outcome == 'Target': ls_stats[t.direction]['wins'] += 1
    
    long_wr = round(ls_stats['Long']['wins']/ls_stats['Long']['total']*100, 1) if ls_stats['Long']['total'] > 0 else 0
    short_wr = round(ls_stats['Short']['wins']/ls_stats['Short']['total']*100, 1) if ls_stats['Short']['total'] > 0 else 0

    # Dati Grafici Standard
    chart_labels, chart_data = [], []
    run_tot = 0
    for t in sorted(active_trades, key=lambda x: x.date):
        run_tot += t.result_percent
        chart_labels.append(t.date.strftime('%d/%m'))
        chart_data.append(round(run_tot, 2))

    return render_template('statistics.html', no_data=False, user=current_user, admin_view=admin_view,
                           win_rate=win_rate, profit_factor=profit_factor, net_result=net_result, expectancy=expectancy,
                           total_active=total_active, num_wins=num_wins, num_losses=num_losses,
                           asset_table=asset_table,
                           day_labels=json.dumps(day_labels), day_data=json.dumps(day_data),
                           ls_stats=ls_stats, long_wr=long_wr, short_wr=short_wr,
                           chart_labels=json.dumps(chart_labels), chart_data=json.dumps(chart_data))

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
        flash('Eliminato.', 'success')
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