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
ADMIN_USER = "Matteo" 

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
    trading_rules = db.Column(db.Text, default="1. Attendi chiusura candela\n2. Non tradare durante news rosse")
    risk_rules = db.Column(db.Text, default="1. Max 1% rischio per trade\n2. Max 3 stop loss al giorno")
    custom_pairs = db.Column(db.Text, default="") 

class JournalEntry(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    pair = db.Column(db.String(20), nullable=False)
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
        current_user.trading_rules = request.form.get('trading_rules')
        current_user.risk_rules = request.form.get('risk_rules')
        current_user.custom_pairs = request.form.get('custom_pairs')
        db.session.commit()
        flash('Setup aggiornato!', 'success')
        return redirect(url_for('settings'))
    
    u_pros = current_user.pros_settings.split(',') if current_user.pros_settings else []
    u_cons = current_user.cons_settings.split(',') if current_user.cons_settings else []
    while len(u_pros) < 7: u_pros.append("")
    while len(u_cons) < 7: u_cons.append("")
    return render_template('settings.html', user_pros=u_pros, user_cons=u_cons, user=current_user)

@app.route('/rules', methods=['GET', 'POST'])
@login_required
def rules():
    if request.method == 'POST':
        current_user.trading_rules = request.form.get('trading_rules')
        current_user.risk_rules = request.form.get('risk_rules')
        db.session.commit()
        flash('Regole aggiornate!', 'success')
        return redirect(url_for('rules'))
    return render_template('rules.html', user=current_user)

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

    filtered_trades = query.all()
    filter_stats = {'total': len(filtered_trades), 'net_profit': 0, 'win_rate': 0, 'avg_rr': 0, 'wins': 0, 'loss': 0, 'be': 0}
    
    if filtered_trades:
        active = [t for t in filtered_trades if t.outcome in ['Target', 'Stop Loss', 'Breakeven']]
        wins = [t for t in active if t.outcome == 'Target']
        losses = [t for t in active if t.outcome == 'Stop Loss']
        
        filter_stats['net_profit'] = round(sum((t.result_percent or 0) for t in filtered_trades), 2)
        filter_stats['wins'] = len(wins)
        filter_stats['loss'] = len(losses)
        filter_stats['be'] = len([t for t in active if t.outcome == 'Breakeven'])
        
        if len(active) > 0: filter_stats['win_rate'] = round((len(wins) / len(active)) * 100, 1)
        
        rrs = [t.rr_final for t in filtered_trades if t.rr_final is not None and t.rr_final > 0]
        if rrs: filter_stats['avg_rr'] = round(sum(rrs) / len(rrs), 2)

    page = request.args.get('page', 1, type=int)
    pagination = query.order_by(JournalEntry.date.desc()).paginate(page=page, per_page=15, error_out=False)
    
    u_pros = [p for p in (current_user.pros_settings.split(',') if current_user.pros_settings else []) if p]
    u_cons = [c for c in (current_user.cons_settings.split(',') if current_user.cons_settings else []) if c]
    custom_pairs_list = [p.strip().upper() for p in (current_user.custom_pairs.split(',') if current_user.custom_pairs else []) if p.strip()]

    return render_template('dashboard.html', pagination=pagination, admin_view=(current_user.role == 'admin'), 
                           user=current_user, user_pros=u_pros, user_cons=u_cons, 
                           filter_stats=filter_stats, custom_pairs=custom_pairs_list)

@app.route('/statistics')
@login_required
def statistics_page():
    admin_view = (current_user.role == 'admin')
    base_query = JournalEntry.query
    if not admin_view:
        base_query = base_query.filter_by(user_id=current_user.id)
    
    trades = base_query.order_by(JournalEntry.date.asc()).all()
    if not trades: return render_template('statistics.html', no_data=True, user=current_user, admin_view=admin_view)

    active_trades = [t for t in trades if t.outcome in ['Target', 'Stop Loss', 'Breakeven']]
    wins = [(t.result_percent or 0) for t in active_trades if t.outcome == 'Target']
    losses = [(t.result_percent or 0) for t in active_trades if t.outcome == 'Stop Loss']
    
    total_active = len(active_trades)
    num_wins = len(wins)
    num_losses = len(losses)
    
    win_rate = round((num_wins / total_active * 100), 2) if total_active > 0 else 0
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    net_result = round(gross_profit - gross_loss, 2)
    profit_factor = round(gross_profit / gross_loss, 2) if gross_loss > 0 else round(gross_profit, 2)

    unique_days = len(set(t.date.strftime('%Y-%m-%d') for t in trades))
    
    avg_weekly_trades = 0
    if trades:
        delta = (trades[-1].date - trades[0].date).days
        weeks = max(1, delta / 7)
        avg_weekly_trades = round(len(trades) / weeks, 1)

    returns = [(t.result_percent or 0) for t in active_trades]
    std_dev = round(statistics.stdev(returns), 2) if len(returns) > 1 else 0
    avg_return = statistics.mean(returns) if returns else 0
    sharpe_ratio = round(avg_return / std_dev, 2) if std_dev > 0 else 0
    
    avg_win = round(statistics.mean(wins), 2) if wins else 0
    avg_loss = round(statistics.mean(losses), 2) if losses else 0
    avg_rr_realized = round(avg_win / abs(avg_loss), 2) if avg_loss != 0 else 0
    
    expectancy = 0
    if total_active > 0:
        win_rate_dec = num_wins / total_active
        loss_rate_dec = num_losses / total_active
        expectancy = round((win_rate_dec * avg_win) - (loss_rate_dec * abs(avg_loss)), 2)

    # TABELLA EMOZIONI
    emo_stats = {}
    for t in trades:
        emo = t.emotions if t.emotions else "Nessuna"
        if emo not in emo_stats: emo_stats[emo] = {'total':0, 'wins':0, 'res':0}
        emo_stats[emo]['total'] += 1
        emo_stats[emo]['res'] += (t.result_percent or 0)
        if t.outcome == 'Target': emo_stats[emo]['wins'] += 1
    
    emo_table = []
    for emo, data in emo_stats.items():
        wr = round(data['wins']/data['total']*100, 1) if data['total'] > 0 else 0
        emo_table.append({'name': emo, 'total': data['total'], 'win_rate': wr, 'result': round(data['res'], 2)})
    emo_table.sort(key=lambda x: x['result'], reverse=True)

    # 5. CONFLUENZE (AGGIORNATO CON DETTAGLIO TARGET/STOP/BE)
    tag_stats = {} 
    for t in active_trades:
        tags = []
        if t.selected_pros: tags.extend([p.strip() for p in t.selected_pros.split(',') if p.strip()])
        if t.selected_cons: tags.extend([c.strip() for c in t.selected_cons.split(',') if c.strip()])
        
        for tag in tags:
            if tag not in tag_stats: tag_stats[tag] = {'total':0, 'wins':0, 'loss':0, 'be':0}
            tag_stats[tag]['total'] += 1
            if t.outcome == 'Target': tag_stats[tag]['wins'] += 1
            elif t.outcome == 'Stop Loss': tag_stats[tag]['loss'] += 1
            elif t.outcome == 'Breakeven': tag_stats[tag]['be'] += 1

    confluence_table = []
    for tag, data in tag_stats.items():
        wr = round(data['wins']/data['total']*100, 1) if data['total']>0 else 0
        # Ora passiamo tutti i dati singoli
        confluence_table.append({'name': tag, 'total': data['total'], 'wins': data['wins'], 'loss': data['loss'], 'be': data['be'], 'win_rate': wr})
    confluence_table.sort(key=lambda x: x['total'], reverse=True)

    # 6. STATISTICHE TIMEFRAME (AGGIORNATO CON DETTAGLIO TARGET/STOP/BE)
    tf_stats = {}
    for t in active_trades:
        if t.timeframe:
            for tf in t.timeframe.split(','):
                tf = tf.strip()
                if tf not in tf_stats: tf_stats[tf] = {'total': 0, 'wins': 0, 'loss': 0, 'be': 0, 'result': 0.0}
                tf_stats[tf]['total'] += 1
                tf_stats[tf]['result'] += (t.result_percent or 0)
                if t.outcome == 'Target': tf_stats[tf]['wins'] += 1
                elif t.outcome == 'Stop Loss': tf_stats[tf]['loss'] += 1
                elif t.outcome == 'Breakeven': tf_stats[tf]['be'] += 1
    
    tf_table = []
    for tf, data in tf_stats.items():
        wr = round(data['wins']/data['total']*100, 1) if data['total'] > 0 else 0
        tf_table.append({'name': tf, 'total': data['total'], 'wins': data['wins'], 'loss': data['loss'], 'be': data['be'], 'win_rate': wr, 'result': round(data['result'], 2)})
    tf_table.sort(key=lambda x: x['total'], reverse=True)

    ls_stats = {'Long': {'total':0, 'wins':0, 'res':0}, 'Short': {'total':0, 'wins':0, 'res':0}}
    for t in active_trades:
        if t.direction in ls_stats:
            ls_stats[t.direction]['total'] += 1
            ls_stats[t.direction]['res'] += (t.result_percent or 0)
            if t.outcome == 'Target': ls_stats[t.direction]['wins'] += 1
    
    long_wr = round(ls_stats['Long']['wins']/ls_stats['Long']['total']*100, 1) if ls_stats['Long']['total'] > 0 else 0
    short_wr = round(ls_stats['Short']['wins']/ls_stats['Short']['total']*100, 1) if ls_stats['Short']['total'] > 0 else 0

    ai_insights = []
    if win_rate < 40: ai_insights.append(f"Il tuo Win Rate ({win_rate}%) è basso. Seleziona meglio i trade.")
    elif win_rate > 60: ai_insights.append(f"Ottimo Win Rate ({win_rate}%)! La direzione è giusta.")
    if profit_factor < 1: ai_insights.append("Profit Factor < 1. Stai perdendo soldi. Taglia le perdite prima.")
    if avg_loss < -1.5: ai_insights.append(f"Stop medi troppo alti ({avg_loss}%). Riduci il rischio per trade.")
    if emo_table:
        worst = emo_table[-1]
        if worst['result'] < 0: ai_insights.append(f"Quando provi '{worst['name']}', perdi spesso. Attenzione alla psicologia.")

    hourly_dist = {h: {'Target': 0, 'Stop Loss': 0, 'Breakeven': 0} for h in range(24)}
    for t in active_trades:
        if t.time:
            try:
                h = int(t.time.split(':')[0])
                if t.outcome in ['Target', 'Stop Loss', 'Breakeven']: hourly_dist[h][t.outcome] += 1
            except: pass
    
    hours_labels = [f"{h:02d}:00" for h in range(24)]
    data_target = [hourly_dist[h]['Target'] for h in range(24)]
    data_stop = [hourly_dist[h]['Stop Loss'] for h in range(24)]
    data_be = [hourly_dist[h]['Breakeven'] for h in range(24)]

    chart_labels, chart_data = [], []
    run_tot = 0
    chronological = sorted(active_trades, key=lambda x: x.date)
    for t in chronological:
        run_tot += (t.result_percent or 0)
        chart_labels.append(t.date.strftime('%d/%m'))
        chart_data.append(round(run_tot, 2))

    day_map = {0: 'Lun', 1: 'Mar', 2: 'Mer', 3: 'Gio', 4: 'Ven', 5: 'Sab', 6: 'Dom'}
    day_stats = {d: {'wins': 0, 'total': 0, 'res': 0} for d in day_map.values()}
    for t in active_trades:
        d = day_map[t.date.weekday()]
        day_stats[d]['total'] += 1
        day_stats[d]['res'] += (t.result_percent or 0)
        if t.outcome == 'Target': day_stats[d]['wins'] += 1
    
    day_table = []
    for d, data in day_stats.items():
        if data['total'] > 0:
            wr = round(data['wins']/data['total']*100, 1)
            day_table.append({'name': d, 'total': data['total'], 'win_rate': wr, 'res': round(data['res'], 2)})
    day_table.sort(key=lambda x: x['res'], reverse=True)

    return render_template('statistics.html', no_data=False, user=current_user, admin_view=admin_view,
                           win_rate=win_rate, profit_factor=profit_factor, net_result=net_result, expectancy=expectancy,
                           unique_days=unique_days, avg_weekly_trades=avg_weekly_trades, std_dev=std_dev, sharpe_ratio=sharpe_ratio, avg_rr_realized=avg_rr_realized,
                           total_active=total_active, total_trades=len(trades), num_wins=num_wins, num_losses=num_losses, num_non_fill=len([t for t in trades if t.outcome=='Non Fillato']), num_setup=len([t for t in trades if t.outcome=='Setup']),
                           confluence_table=confluence_table, emo_table=emo_table, ai_insights=ai_insights,
                           ls_stats=ls_stats, long_wr=long_wr, short_wr=short_wr, day_table=day_table, tf_table=tf_table,
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
    custom_pairs_list = [p.strip().upper() for p in (current_user.custom_pairs.split(',') if current_user.custom_pairs else []) if p.strip()]

    return render_template('edit_trade.html', trade=trade, curr_tfs=curr_tfs, curr_pros=curr_pros, curr_cons=curr_cons, 
                           user_pros_list=u_pros, user_cons_list=u_cons, custom_pairs=custom_pairs_list,
                           val_link1=cur_lnks[0] if len(cur_lnks)>0 else '', val_link2=cur_lnks[1] if len(cur_lnks)>1 else '')

with app.app_context(): db.create_all()
if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5001))
    app.run(host="0.0.0.0", port=port)