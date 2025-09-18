from flask import Flask, render_template, request, redirect, url_for, flash, send_file
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin, LoginManager, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from sqlalchemy import func, and_
from datetime import datetime
import csv
import io

# Create a Flask application instance
app = Flask(__name__)
app.config['SECRET_KEY'] = 'your_super_secret_key_here' # IMPORTANT: Change this!

# --- Database Configuration ---
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///inventory.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# --- Flask-Login Configuration ---
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# --- Database Models ---
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

class Product(db.Model):
    __tablename__ = 'product'
    id = db.Column(db.String(50), primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True)
    def __repr__(self):
        return f'<Product {self.name}>'

class Location(db.Model):
    __tablename__ = 'location'
    id = db.Column(db.String(50), primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True)
    def __repr__(self):
        return f'<Location {self.name}>'

class ProductMovement(db.Model):
    __tablename__ = 'product_movement'
    id = db.Column(db.Integer, primary_key=True)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    from_location = db.Column(db.String(50), db.ForeignKey('location.id'), nullable=True)
    to_location = db.Column(db.String(50), db.ForeignKey('location.id'), nullable=True)
    product_id = db.Column(db.String(50), db.ForeignKey('product.id'), nullable=False)
    qty = db.Column(db.Integer, nullable=False)

    product = db.relationship('Product', backref='movements', lazy=True)
    from_location_obj = db.relationship('Location', foreign_keys=[from_location], backref='from_movements', lazy=True)
    to_location_obj = db.relationship('Location', foreign_keys=[to_location], backref='to_movements', lazy=True)
    def __repr__(self):
        return f'<Movement {self.id}>'

# --- Utility Functions ---
def get_balance_report(product_id=None, location_id=None):
    balance_data = {}
    movements_query = ProductMovement.query.order_by(ProductMovement.timestamp)

    if product_id:
        movements_query = movements_query.filter(ProductMovement.product_id == product_id)
    if location_id:
        movements_query = movements_query.filter(
            (ProductMovement.from_location == location_id) | (ProductMovement.to_location == location_id)
        )

    for movement in movements_query.all():
        if movement.to_location:
            key = (movement.product_id, movement.to_location)
            balance_data[key] = balance_data.get(key, 0) + movement.qty
        if movement.from_location:
            key = (movement.product_id, movement.from_location)
            balance_data[key] = balance_data.get(key, 0) - movement.qty

    report_list = []
    locations_dict = {loc.id: loc.name for loc in Location.query.all()}
    products_dict = {prod.id: prod.name for prod in Product.query.all()}
    
    for (prod_id, loc_id), qty in balance_data.items():
        if qty > 0:
            report_list.append({
                'product_name': products_dict.get(prod_id, 'Unknown Product'),
                'location_name': locations_dict.get(loc_id, 'Unknown Location'),
                'total_qty': qty
            })
    return report_list

# --- Authentication Routes ---
@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('home'))
    if request.method == 'POST':
        user = User.query.filter_by(username=request.form['username']).first()
        if user and user.check_password(request.form['password']):
            login_user(user)
            flash('Logged in successfully.', 'success')
            return redirect(url_for('home'))
        else:
            flash('Invalid username or password.', 'error')
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('You have been logged out.', 'info')
    return redirect(url_for('login'))

# --- Main Routes (Protected) ---
@app.route('/')
@login_required
def home():
    report_data = get_balance_report()
    low_stock_threshold = 10
    low_stock_items = [item for item in report_data if item['total_qty'] < low_stock_threshold]
    total_unique_products = len(Product.query.all())
    total_unique_locations = len(Location.query.all())
    total_movements = len(ProductMovement.query.all())
    
    # Data for Chart.js
    chart_data = db.session.query(
        func.strftime('%Y-%m-%d', ProductMovement.timestamp), 
        func.count(ProductMovement.id)
    ).group_by(func.strftime('%Y-%m-%d', ProductMovement.timestamp)).all()
    
    chart_labels = [c[0] for c in chart_data]
    chart_values = [c[1] for c in chart_data]

    return render_template(
        'index.html',
        low_stock_items=low_stock_items,
        total_products=total_unique_products,
        total_locations=total_unique_locations,
        total_movements=total_movements,
        chart_labels=chart_labels,
        chart_values=chart_values
    )

@app.route('/products', methods=['GET', 'POST'])
@login_required
def products():
    if request.method == 'POST':
        product_id = request.form['product_id']
        name = request.form['name']
        if not product_id or not name:
            flash('Both Product ID and Name are required.', 'error')
        elif Product.query.get(product_id):
            flash('Product ID already exists.', 'error')
        else:
            new_product = Product(id=product_id, name=name)
            db.session.add(new_product)
            db.session.commit()
            flash('Product added successfully!', 'success')
        return redirect(url_for('products'))
        
    search_query = request.args.get('search', '')
    if search_query:
        all_products = Product.query.filter(Product.name.like(f'%{search_query}%')).all()
    else:
        all_products = Product.query.all()
    
    return render_template('product.html', products=all_products, search_query=search_query)

@app.route('/products/edit/<string:product_id>', methods=['GET', 'POST'])
@login_required
def edit_product(product_id):
    product = Product.query.get_or_404(product_id)
    if request.method == 'POST':
        product.name = request.form['name']
        db.session.commit()
        flash('Product updated successfully!', 'success')
        return redirect(url_for('products'))
    return render_template('edit_product.html', product=product)

@app.route('/products/delete/<string:product_id>', methods=['POST'])
@login_required
def delete_product(product_id):
    product = Product.query.get_or_404(product_id)
    db.session.delete(product)
    db.session.commit()
    flash('Product deleted successfully!', 'success')
    return redirect(url_for('products'))

@app.route('/locations', methods=['GET', 'POST'])
@login_required
def locations():
    if request.method == 'POST':
        location_id = request.form['location_id']
        name = request.form['name']
        if not location_id or not name:
            flash('Both Location ID and Name are required.', 'error')
        elif Location.query.get(location_id):
            flash('Location ID already exists.', 'error')
        else:
            new_location = Location(id=location_id, name=name)
            db.session.add(new_location)
            db.session.commit()
            flash('Location added successfully!', 'success')
        return redirect(url_for('locations'))

    search_query = request.args.get('search', '')
    if search_query:
        all_locations = Location.query.filter(Location.name.like(f'%{search_query}%')).all()
    else:
        all_locations = Location.query.all()
        
    return render_template('location.html', locations=all_locations, search_query=search_query)

@app.route('/locations/edit/<string:location_id>', methods=['GET', 'POST'])
@login_required
def edit_location(location_id):
    location = Location.query.get_or_404(location_id)
    if request.method == 'POST':
        location.name = request.form['name']
        db.session.commit()
        flash('Location updated successfully!', 'success')
        return redirect(url_for('locations'))
    return render_template('edit_location.html', location=location)

@app.route('/locations/delete/<string:location_id>', methods=['POST'])
@login_required
def delete_location(location_id):
    location = Location.query.get_or_404(location_id)
    db.session.delete(location)
    db.session.commit()
    flash('Location deleted successfully!', 'success')
    return redirect(url_for('locations'))

@app.route('/movements', methods=['GET', 'POST'])
@login_required
def movements():
    if request.method == 'POST':
        product_id = request.form['product_id']
        from_location = request.form['from_location'] or None
        to_location = request.form['to_location'] or None
        qty = int(request.form['qty'])

        if not from_location and not to_location:
            flash("A movement must have a 'from' or 'to' location.", 'error')
            return redirect(url_for('movements'))
        
        # Validation for 'Out' movements
        if from_location and not to_location:
            current_balance = sum(item['total_qty'] for item in get_balance_report(product_id=product_id, location_id=from_location))
            if qty > current_balance:
                flash(f"Error: Not enough stock to move. Current balance is {current_balance}.", 'error')
                return redirect(url_for('movements'))
        
        new_movement = ProductMovement(
            product_id=product_id,
            from_location=from_location,
            to_location=to_location,
            qty=qty
        )
        db.session.add(new_movement)
        db.session.commit()
        flash('Movement recorded successfully!', 'success')
        return redirect(url_for('movements'))
        
    all_products = Product.query.all()
    all_locations = Location.query.all()
    all_movements = ProductMovement.query.order_by(ProductMovement.timestamp.desc()).all()
    return render_template(
        'movement.html',
        products=all_products,
        locations=all_locations,
        movements=all_movements
    )

@app.route('/movements/edit/<int:movement_id>', methods=['GET', 'POST'])
@login_required
def edit_movement(movement_id):
    movement = ProductMovement.query.get_or_404(movement_id)
    all_products = Product.query.all()
    all_locations = Location.query.all()

    if request.method == 'POST':
        movement.product_id = request.form['product_id']
        movement.from_location = request.form['from_location'] or None
        movement.to_location = request.form['to_location'] or None
        movement.qty = int(request.form['qty'])
        db.session.commit()
        flash('Movement updated successfully!', 'success')
        return redirect(url_for('movements'))
    
    return render_template(
        'edit_movement.html',
        movement=movement,
        products=all_products,
        locations=all_locations
    )

@app.route('/movements/delete/<int:movement_id>', methods=['POST'])
@login_required
def delete_movement(movement_id):
    movement = ProductMovement.query.get_or_404(movement_id)
    db.session.delete(movement)
    db.session.commit()
    flash('Movement deleted successfully!', 'success')
    return redirect(url_for('movements'))

# --- Report Routes ---
@app.route('/report', methods=['GET'])
@login_required
def report():
    product_id = request.args.get('product_id')
    location_id = request.args.get('location_id')
    
    report_list = get_balance_report(product_id, location_id)
    
    all_products = Product.query.all()
    all_locations = Location.query.all()

    return render_template(
        'report.html', 
        report_data=report_list, 
        products=all_products, 
        locations=all_locations,
        selected_product=product_id,
        selected_location=location_id
    )

@app.route('/report/export_csv')
@login_required
def export_report_csv():
    report_data = get_balance_report()
    si = io.StringIO()
    cw = csv.writer(si)
    cw.writerow(['Product', 'Location', 'Quantity'])
    for item in report_data:
        cw.writerow([item['product_name'], item['location_name'], item['total_qty']])
    
    output = io.BytesIO()
    output.write(si.getvalue().encode('utf-8'))
    output.seek(0)
    
    return send_file(
        output,
        mimetype='text/csv',
        as_attachment=True,
        download_name='inventory_report.csv'
    )

# --- Initial setup for a default user ---
def create_initial_user():
    if not User.query.filter_by(username='admin').first():
        admin_user = User(username='admin')
        admin_user.set_password('password') # Change this password!
        db.session.add(admin_user)
        db.session.commit()
        print("Default user 'admin' with password 'password' created.")


if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        create_initial_user()
    app.run(debug=True)