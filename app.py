from flask import Flask, request, jsonify, session, send_file, render_template
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from flask.views import MethodView
from datetime import datetime, timedelta
import os
import uuid
from flask_cors import CORS
from flask_migrate import Migrate
import os
from werkzeug.utils import secure_filename
from datetime import datetime
from datetime import date


app = Flask(__name__, template_folder='Templates')
CORS(app)

app.config['SECRET_KEY'] = os.urandom(24)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///property_management.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = 'uploads'
UPLOAD_FOLDER = os.path.join('static', 'images', 'properties')
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}


UPLOAD_FOLDER = os.path.join(os.getcwd(), 'static/documents')
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER


os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)



# Make sure the upload directory exists
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)


db = SQLAlchemy(app)
app.app_context().push()
migrate = Migrate(app, db)
# Helper functions
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def validate_dates(start_date, end_date):
    try:
        start = datetime.strptime(start_date, '%Y-%m-%d')
        end = datetime.strptime(end_date, '%Y-%m-%d')
        return start < end
    except ValueError:
        return False

# Models
class User(db.Model):
    __tablename__ = 'users'
    
    user_id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    phone_number = db.Column(db.String(20), nullable=False)
    properties = db.relationship('Property', backref='owner', lazy=True)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    @classmethod
    def create(cls, full_name, email, password, phone_number):
        user = cls(
            full_name=full_name,
            email=email,
            phone_number=phone_number
        )
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        return user

class Property(db.Model):
    __tablename__ = 'properties'
    
    property_id = db.Column(db.String(20), primary_key=True, default=lambda: str(uuid.uuid4())[:20])
    user_id = db.Column(db.Integer, db.ForeignKey('users.user_id'), nullable=False)
    property_type = db.Column(db.String(50), nullable=False)
    street_name = db.Column(db.String(100), nullable=False)
    city = db.Column(db.String(100), nullable=False)
    building_details = db.Column(db.Text)
    size_sqft = db.Column(db.Float, nullable=False)
    bedrooms = db.Column(db.Integer, nullable=False)
    occupancy_status = db.Column(db.String(20), default='vacant')
    current_occupancy = db.relationship('Occupancy', backref='property', uselist=False)
    documents = db.relationship('Document', backref='property', lazy=True)
    notifications = db.relationship('Notification', backref='property', lazy=True)
    rent_per_month = db.Column(db.Float, nullable=False)
    units = db.Column(db.Integer, nullable=False)
    image = db.Column(db.String(255))

    def add_occupancy(self, tenant_data):
        if self.occupancy_status == 'occupied':
            raise ValueError("Property is already occupied")
        
        occupancy = Occupancy(
            property_id=self.property_id,
            tenant_name=tenant_data['tenant_name'],
            tenant_phone=tenant_data['tenant_phone'],
            tenant_email=tenant_data['tenant_email'],
            lease_start_date=tenant_data['lease_start_date'],
            lease_end_date=tenant_data['lease_end_date'],
            total_rent=tenant_data['total_rent']
        )
        self.occupancy_status = 'occupied'
        db.session.add(occupancy)
        db.session.commit()
        return occupancy

    def get_income_summary(self):
        if not self.current_occupancy:
            return {
                'total_rent': 0,
                'total_paid': 0,
                'total_due': 0,
                'payment_percentage': 0,
                'overdue_amount': 0
            }
            
        today = datetime.now().date()
        total_paid = sum(p.amount for p in self.current_occupancy.payments if p.status == 'paid')
        total_due = sum(p.amount for p in self.current_occupancy.payments if p.status == 'due')
        
        # Calculate overdue amount (due payments with due_date < today)
        overdue_amount = sum(
            p.amount 
            for p in self.current_occupancy.payments 
            if p.status == 'due' and p.due_date < today
        )

        return {
            'total_rent': self.current_occupancy.total_rent,
            'total_paid': total_paid,
            'total_due': total_due,
            'payment_percentage': (total_paid / self.current_occupancy.total_rent * 100),
            'overdue_amount': overdue_amount,
            'overdue_payments': [
                {
                    'amount': float(p.amount),
                    'due_date': p.due_date.strftime('%Y-%m-%d')
                }
                for p in self.current_occupancy.payments
                if p.status == 'due' and p.due_date < today
            ]
        }

class Occupancy(db.Model):
    __tablename__ = 'occupancy'
    
    occupancy_id = db.Column(db.Integer, primary_key=True)
    property_id = db.Column(db.String(20), db.ForeignKey('properties.property_id'))
    tenant_name = db.Column(db.String(100), nullable=False)
    tenant_phone = db.Column(db.String(20))
    tenant_email = db.Column(db.String(120))
    lease_start_date = db.Column(db.Date, nullable=False)
    lease_end_date = db.Column(db.Date, nullable=False)
    total_rent = db.Column(db.Float, nullable=False)
    payments = db.relationship('Payment', backref='occupancy', lazy=True)

    def generate_payment_schedule(self, number_of_payments):
        payment_amount = self.total_rent / number_of_payments
        start_date = self.lease_start_date
        
        for i in range(number_of_payments):
            due_date = start_date + timedelta(days=(30 * i))
            payment = Payment(
                occupancy_id=self.occupancy_id,
                amount=payment_amount,
                due_date=due_date,
                status='due'
            )
            db.session.add(payment)
        db.session.commit()

    def to_dict(self):
        return {
            'tenant_name': self.tenant_name,
            'tenant_phone': self.tenant_phone,
            'tenant_email': self.tenant_email,
            'lease_start_date': self.lease_start_date.strftime('%Y-%m-%d'),
            'lease_end_date': self.lease_end_date.strftime('%Y-%m-%d'),
            'total_rent': self.total_rent
        }

class Payment(db.Model):
    __tablename__ = 'payments'
    
    payment_id = db.Column(db.Integer, primary_key=True)
    occupancy_id = db.Column(db.Integer, db.ForeignKey('occupancy.occupancy_id'))
    amount = db.Column(db.Float, nullable=False)
    due_date = db.Column(db.Date, nullable=False)
    status = db.Column(db.String(20), default='due')

    def mark_as_paid(self):
        self.status = 'paid'
        db.session.commit()

class Document(db.Model):
    __tablename__ = 'documents'
    
    document_id = db.Column(db.Integer, primary_key=True)
    property_id = db.Column(db.String(20), db.ForeignKey('properties.property_id'))
    title = db.Column(db.String(200), nullable=False)
    file_path = db.Column(db.String(500), nullable=False)
    upload_date = db.Column(db.Date, default=datetime.utcnow)

    def to_dict(self):
        return {
            'document_id': self.document_id,
            'title': self.title,
            'upload_date': self.upload_date.strftime('%Y-%m-%d')
        }

class Notification(db.Model):
    __tablename__ = 'notifications'
    
    notification_id = db.Column(db.Integer, primary_key=True)
    property_id = db.Column(db.String(20), db.ForeignKey('properties.property_id'))
    notification_type = db.Column(db.String(50), nullable=False)  # 'lease_renewal' or 'payment'
    notification_period = db.Column(db.Integer, nullable=False)  # 7, 15, or 30 days
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            'notification_id': self.notification_id,
            'notification_type': self.notification_type,
            'notification_period': self.notification_period,
            'is_active': self.is_active
        }

class Dashboard(db.Model):
    __tablename__ = 'dashboard'

    id = db.Column(db.Integer, primary_key=True)
    total_properties = db.Column(db.Integer, nullable=False)
    total_tenants = db.Column(db.Integer, nullable=False)
    total_income = db.Column(db.Float, nullable=False)
    vacant_properties = db.Column(db.Integer, nullable=False)

    @classmethod
    def get_dashboard_data(cls):
        total_properties = Property.query.count()
        total_tenants = Tenant.query.count()
        total_income = sum(payment.amount for payment in Payment.query.filter_by(status='paid'))
        vacant_properties = Property.query.filter_by(occupancy_status='vacant').count()

        return cls(
            total_properties=total_properties,
            total_tenants=total_tenants,
            total_income=total_income,
            vacant_properties=vacant_properties
        )



# Views
class AuthenticatedMethodView(MethodView):
    """Base class for views that require authentication"""
    
    def dispatch_request(self, *args, **kwargs):
        if 'user_id' not in session:
            return jsonify({'error': 'Not authenticated'}), 401
        return super().dispatch_request(*args, **kwargs)

class UserView(MethodView):
    def post(self):
        """Handle user signup"""
        data = request.json
        if not all(k in data for k in ['full_name', 'email', 'password', 'phone_number']):
            return jsonify({'error': 'Missing required fields'}), 400
        
        try:
            user = User.create(
                full_name=data['full_name'],
                email=data['email'],
                password=data['password'],
                phone_number=data['phone_number']
            )
            return jsonify({'message': 'User created successfully'}), 201
        except Exception as e:
            db.session.rollback()
            return jsonify({'error': str(e)}), 400

class LoginView(MethodView):
    def post(self):
        """Handle user login"""
        data = request.json
        

        if not all(k in data for k in ['email', 'password']):
            return jsonify({'error': 'Missing credentials'}), 400

        user = User.query.filter_by(email=data['email']).first()
        if user and user.check_password(data['password']):
            session['user_id'] = user.user_id
            return jsonify({'message': 'Login successful'}), 200
        return jsonify({'error': 'Invalid credentials'}), 401

class PasswordResetView(AuthenticatedMethodView):
    def post(self):
        """Handle password reset"""
        data = request.json
        if not all(k in data for k in ['old_password', 'new_password']):
            return jsonify({'error': 'Missing required fields'}), 400

        user = User.query.get(session['user_id'])
        if not user.check_password(data['old_password']):
            return jsonify({'error': 'Invalid old password'}), 400

        try:
            user.set_password(data['new_password'])
            db.session.commit()
            return jsonify({'message': 'Password updated successfully'}), 200
        except Exception as e:
            db.session.rollback()
            return jsonify({'error': str(e)}), 400

class PropertyView(AuthenticatedMethodView):
    def post(self):
        """Add a new property"""
        if 'user_id' not in session:
            return jsonify({'error': 'User not logged in'}), 401

        data = request.json

        # Ensure required fields are present
        required_fields = ['property_type', 'street_name', 'city', 'size_sqft', 'bedrooms', 'units', 'rent_per_month']
        missing_fields = [field for field in required_fields if field not in data]
        if missing_fields:
            return jsonify({'error': f"Missing fields: {', '.join(missing_fields)}"}), 400

        try:
            # Create the new property with occupancy_status always set to 'vacant'
            new_property = Property(
                user_id=session['user_id'],
                property_type=data['property_type'],
                street_name=data['street_name'],
                city=data['city'],
                building_details=data.get('building_details'),  # Optional
                size_sqft=float(data['size_sqft']),
                bedrooms=int(data['bedrooms']),
                units=int(data['units']),
                rent_per_month=float(data['rent_per_month']),
                occupancy_status='vacant',  # Always set to vacant for new properties
                image='default.jpg'
            )

            db.session.add(new_property)
            db.session.commit()

            return jsonify({
                'message': 'Property added successfully',
                'property_id': new_property.property_id
            }), 201

        except Exception as e:
            db.session.rollback()
            return jsonify({'error': f"Failed to add property: {str(e)}"}), 500
    def get(self):
        """Get all properties for the logged-in user"""
        if 'user_id' not in session:
            return jsonify({'error': 'User not logged in'}), 401

        # Fetch properties belonging to the logged-in user
        user_id = session['user_id']
        properties = Property.query.filter_by(user_id=user_id).all()

        if not properties:
            print('properties does not exist')
            return render_template('properties.html', properties=[])

        # Convert properties to dictionaries
        properties_data = [
            {
                'property_id': p.property_id,
                'property_type': p.property_type,
                'street_name': p.street_name,
                'city': p.city,
                'size_sqft': p.size_sqft,
                'bedrooms': p.bedrooms,
                'rent_per_month': p.rent_per_month,
                'units': p.units,
                'occupancy_status': p.occupancy_status,
                'building_details': p.building_details,
                # Use default image if no image is provided
                'image': 'default.jpg'  # Replace this with p.image if image uploads are implemented
            }
            for p in properties
        ]
        return jsonify(properties_data), 200

class PropertyDetailView(AuthenticatedMethodView):
    def get(self, property_id):
        """Get details for a specific property"""
        property = Property.query.filter_by(
            property_id=property_id, 
            user_id=session['user_id']
        ).first_or_404()

        return jsonify({
            'property_id': property.property_id,
            'property_type': property.property_type,
            'street_name': property.street_name,
            'city': property.city,
            'building_details': property.building_details,
            'size_sqft': property.size_sqft,
            'bedrooms': property.bedrooms,
            'units': property.units,
            'rent_per_month': property.rent_per_month,
            'occupancy_status': property.occupancy_status
        }), 200
        
        # return jsonify({
        #     'property': {
        #         'property_id': property.property_id,
        #         'property_type': property.property_type,
        #         'street_name': property.street_name,
        #         'city': property.city,
        #         'building_details': property.building_details,
        #         'size_sqft': property.size_sqft,
        #         'bedrooms': property.bedrooms,
        #         'occupancy_status': property.occupancy_status
        #     },
        #     'occupancy': property.current_occupancy.to_dict() if property.current_occupancy else None,
        #     'income_summary': property.get_income_summary()
        # }), 200

    def put(self, property_id):
        """Update a property"""
        property = Property.query.filter_by(
            property_id=property_id, 
            user_id=session['user_id']
        ).first_or_404()

        data = request.json
        try:
            for key, value in data.items():
                if hasattr(property, key):
                    setattr(property, key, value)
            db.session.commit()
            return jsonify({'message': 'Property updated successfully'}), 200
        except Exception as e:
            db.session.rollback()
            return jsonify({'error': str(e)}), 400

    def delete(self, property_id):
        """Delete a property"""
        property = Property.query.filter_by(
            property_id=property_id, 
            user_id=session['user_id']
        ).first_or_404()

        if property.current_occupancy:
            return jsonify({
                'warning': 'Property has active occupancy. Confirm deletion?',
                'requires_confirmation': True
            }), 200

        try:
            db.session.delete(property)
            db.session.commit()
            return jsonify({'message': 'Property deleted successfully'}), 200
        except Exception as e:
            db.session.rollback()
            return jsonify({'error': str(e)}), 400

class OccupancyView(AuthenticatedMethodView):
    def post(self, property_id):
        """Add new occupancy to a property"""
        try:
            property = Property.query.filter_by(
                property_id=property_id, 
                user_id=session['user_id']
            ).first_or_404()

            if property.occupancy_status != 'vacant':
                return jsonify({'error': 'Property is not vacant'}), 400

            data = request.json
            self.validate_occupancy_data(data)

            # Begin transaction
            db.session.begin_nested()

            try:
                # Create occupancy record
                occupancy = Occupancy(
                    property_id=property_id,
                    tenant_name=data['tenant_name'],
                    tenant_phone=data['tenant_phone'],
                    tenant_email=data['tenant_email'],
                    lease_start_date=datetime.strptime(data['lease_start_date'], '%Y-%m-%d'),
                    lease_end_date=datetime.strptime(data['lease_end_date'], '%Y-%m-%d'),
                    total_rent=float(data['total_rent'])
                )
                db.session.add(occupancy)
                db.session.flush()  # Get occupancy_id

                # Generate payment schedule
                payment_amount = data['total_rent'] / data['number_of_payments']
                start_date = datetime.strptime(data['lease_start_date'], '%Y-%m-%d')

                payment_statuses = data.get('payments', [])

                for i in range(data['number_of_payments']):
                    due_date = start_date + timedelta(days=(30 * i))

                    payment_status = 'due'
                    if i < len(payment_statuses):
                        # Extract just the status string from the payment data
                        payment_status = payment_statuses[i].get('status', 'due')

                    payment = Payment(
                        occupancy_id=occupancy.occupancy_id,
                        amount=payment_amount,
                        due_date=due_date,
                        status=payment_status
                    )
                    db.session.add(payment)
                # Update property status
                property.occupancy_status = 'occupied'
                
                # Commit transaction
                db.session.commit()

                return jsonify({
                    'message': 'Occupancy added successfully',
                    'occupancy_id': occupancy.occupancy_id,
                    'payment_schedule': [{
                        'due_date': payment.due_date.strftime('%Y-%m-%d'),
                        'amount': payment.amount,
                        'status': payment.status
                    } for payment in occupancy.payments]
                }), 201

            except Exception as e:
                db.session.rollback()
                raise e

        except ValueError as e:
            return jsonify({'error': str(e)}), 400
        except Exception as e:
            return jsonify({'error': f"Failed to add occupancy: {str(e)}"}), 500

    def put(self, property_id):
        """Update occupancy details"""
        property = Property.query.filter_by(
            property_id=property_id, 
            user_id=session['user_id']
        ).first_or_404()

        if not property.current_occupancy:
            return jsonify({'error': 'No active occupancy found'}), 404

        data = request.json
        try:
            occupancy = property.current_occupancy
            for key, value in data.items():
                if hasattr(occupancy, key):
                    setattr(occupancy, key, value)
            db.session.commit()
            return jsonify({'message': 'Occupancy updated successfully'}), 200
        except Exception as e:
            db.session.rollback()
            return jsonify({'error': str(e)}), 400

    def delete(self, property_id):
        """End occupancy"""
        property = Property.query.filter_by(
            property_id=property_id, 
            user_id=session['user_id']
        ).first_or_404()

        if not property.current_occupancy:
            return jsonify({'error': 'No active occupancy found'}), 404

        try:
            db.session.delete(property.current_occupancy)
            property.occupancy_status = 'vacant'
            db.session.commit()
            return jsonify({'message': 'Occupancy ended successfully'}), 200
        except Exception as e:
            db.session.rollback()
            return jsonify({'error': str(e)}), 400

    def validate_occupancy_data(self, data):
        """Validate occupancy data"""
        required_fields = [
            'tenant_name', 'tenant_phone', 'tenant_email',
            'lease_start_date', 'lease_end_date', 'total_rent',
            'number_of_payments'
        ]
        
        if not all(field in data for field in required_fields):
            raise ValueError(f"Missing required fields: {', '.join(set(required_fields) - set(data.keys()))}")

        # Validate dates
        try:
            start_date = datetime.strptime(data['lease_start_date'], '%Y-%m-%d')
            end_date = datetime.strptime(data['lease_end_date'], '%Y-%m-%d')
            today = date.today()
            if start_date >= end_date:
                raise ValueError("Lease start date must be before end date")
            if start_date.strftime('%Y-%m-%d') < today.strftime("%%Y-%m-%d"):
                raise ValueError("Lease start date cannot be in the past")
        except ValueError as e:
            raise ValueError(f"Invalid date format: {str(e)}")

        # Validate rent and payments
        if float(data['total_rent']) <= 0:
            raise ValueError("Total rent must be greater than 0")
        if int(data['number_of_payments']) <= 0:
            raise ValueError("Number of payments must be greater than 0")

        return True


      
        
class DocumentView(AuthenticatedMethodView):
    def get(self, property_id):
        """Get all documents for a property"""
        property = Property.query.filter_by(
            property_id=property_id, 
            user_id=session['user_id']
        ).first_or_404()

        return jsonify([doc.to_dict() for doc in property.documents]), 200

    def post(self, property_id):
        """Upload a new document"""
        property = Property.query.filter_by(
            property_id=property_id, 
            user_id=session['user_id']
        ).first_or_404()

        if 'file' not in request.files:
            return jsonify({'error': 'No file provided'}), 400

        file = request.files['file']
        if not file or not allowed_file(file.filename):
            return jsonify({'error': 'Invalid file'}), 400

        try:
            filename = secure_filename(file.filename)
            file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(file_path)

            document = Document(
                property_id=property_id,
                title=request.form.get('title', filename),
                file_path=file_path
            )
            db.session.add(document)
            db.session.commit()
            return jsonify({'message': 'Document uploaded successfully'}), 201
        except Exception as e:
            db.session.rollback()
            return jsonify({'error': str(e)}), 400

class DocumentDetailView(AuthenticatedMethodView):
    def get(self, document_id):
        """Download a document"""
        document = Document.query.join(Property).filter(
            Document.document_id == document_id,
            Property.user_id == session['user_id']
        ).first_or_404()
        
        return send_file(document.file_path, as_attachment=True)

    def delete(self, document_id):
        """Delete a document"""
        document = Document.query.join(Property).filter(
            Document.document_id == document_id,
            Property.user_id == session['user_id']
        ).first_or_404()

        try:
            if os.path.exists(document.file_path):
                os.remove(document.file_path)
            db.session.delete(document)
            db.session.commit()
            return jsonify({'message': 'Document deleted successfully'}), 200
        except Exception as e:
            db.session.rollback()
            return jsonify({'error': str(e)}), 400

class IncomeView(AuthenticatedMethodView):
    def get(self, property_id):
        """Track income for a property"""
        property = Property.query.filter_by(
            property_id=property_id,
            user_id=session['user_id']
        ).first_or_404()
        
        return jsonify(property.get_income_summary()), 200

class NotificationView(AuthenticatedMethodView):
    def post(self, property_id):
        """Set notification preferences"""
        property = Property.query.filter_by(
            property_id=property_id,
            user_id=session['user_id']
        ).first_or_404()

        data = request.json
        if not all(k in data for k in ['notification_type', 'notification_period']):
            return jsonify({'error': 'Missing required fields'}), 400
            
        if data['notification_period'] not in [7, 15, 30]:
            return jsonify({'error': 'Invalid notification period'}), 400
            
        if data['notification_type'] not in ['lease_renewal', 'payment']:
            return jsonify({'error': 'Invalid notification type'}), 400

        try:
            existing = Notification.query.filter_by(
                property_id=property_id,
                notification_type=data['notification_type']
            ).first()
            
            if existing:
                existing.notification_period = data['notification_period']
                existing.is_active = True
            else:
                notification = Notification(
                    property_id=property_id,
                    notification_type=data['notification_type'],
                    notification_period=data['notification_period']
                )
                db.session.add(notification)
                
            db.session.commit()
            return jsonify({'message': 'Notification preferences saved'}), 201
        except Exception as e:
            db.session.rollback()
            return jsonify({'error': str(e)}), 400

    def get(self, property_id):
        """Get notification settings for a property"""
        property = Property.query.filter_by(
            property_id=property_id,
            user_id=session['user_id']
        ).first_or_404()

        notifications = Notification.query.filter_by(
            property_id=property_id,
            is_active=True
        ).all()

        return jsonify([n.to_dict() for n in notifications]), 200

    def delete(self, property_id):
        """Disable notifications for a property"""
        property = Property.query.filter_by(
            property_id=property_id,
            user_id=session['user_id']
        ).first_or_404()

        data = request.json
        if 'notification_type' not in data:
            return jsonify({'error': 'Missing notification type'}), 400

        try:
            notification = Notification.query.filter_by(
                property_id=property_id,
                notification_type=data['notification_type']
            ).first_or_404()
            
            notification.is_active = False
            db.session.commit()
            return jsonify({'message': 'Notification disabled successfully'}), 200
        except Exception as e:
            db.session.rollback()
            return jsonify({'error': str(e)}), 400

class NotificationCheckView(AuthenticatedMethodView):
    def get(self):
        """Check all active notifications"""
        current_date = datetime.now().date()
        
        notifications = (
            Notification.query
            .join(Property)
            .filter(
                Property.user_id == session['user_id'],
                Notification.is_active == True
            )
            .all()
        )

        lease_notifications = []
        payment_notifications = []

        for notification in notifications:
            property = notification.property
            if not property.current_occupancy:
                continue

            if notification.notification_type == 'lease_renewal':
                days_until_end = (property.current_occupancy.lease_end_date - current_date).days
                if 0 <= days_until_end <= notification.notification_period:
                    lease_notifications.append({
                        'property_id': property.property_id,
                        'street_name': property.street_name,
                        'lease_end_date': property.current_occupancy.lease_end_date.strftime('%Y-%m-%d'),
                        'days_remaining': days_until_end
                    })

            elif notification.notification_type == 'payment':
                for payment in property.current_occupancy.payments:
                    if payment.status == 'due':
                        days_until_due = (payment.due_date - current_date).days
                        if 0 <= days_until_due <= notification.notification_period:
                            payment_notifications.append({
                                'property_id': property.property_id,
                                'street_name': property.street_name,
                                'amount': payment.amount,
                                'due_date': payment.due_date.strftime('%Y-%m-%d'),
                                'days_until_due': days_until_due
                            })

        return jsonify({
            'lease_renewals': lease_notifications,
            'payment_dues': payment_notifications
        }), 200

class DashboardView(AuthenticatedMethodView):
    def get(self):
        """Get dashboard summary"""
        try:
            if 'user_id' not in session:
                return jsonify({'error': 'Not authenticated'}), 401

            user_id = session['user_id']
            today = datetime.now().date()

            # Get all properties for the user
            properties = Property.query.filter_by(user_id=user_id).all()
            
            # Property Statistics
            total_properties = len(properties)
            occupied_properties = sum(1 for p in properties if p.occupancy_status == 'occupied')
            vacant_properties = total_properties - occupied_properties
            occupancy_rate = (occupied_properties / total_properties * 100) if total_properties > 0 else 0

            property_stats = {
                'total': total_properties,
                'occupied': occupied_properties,
                'vacant': vacant_properties,
                'occupancy_rate': round(occupancy_rate, 1)
            }

            # Financial Statistics
            total_collected = 0
            total_pending = 0
            total_expected = 0

            for property in properties:
                if property.current_occupancy:
                    total_expected += property.rent_per_month
                    for payment in property.current_occupancy.payments:
                        if payment.status == 'paid':
                            total_collected += payment.amount
                        elif payment.status == 'due':
                            total_pending += payment.amount

            collection_rate = (total_collected / total_expected * 100) if total_expected > 0 else 0
            
            financial_stats = {
                'total_collected': total_collected,
                'total_pending': total_pending,
                'total_expected': total_expected,
                'collection_rate': round(collection_rate, 1)
            }

            # Recent Activities (last 5 payments)
            recent_activities = []
            for property in properties:
                if property.current_occupancy:
                    for payment in sorted(property.current_occupancy.payments, 
                                       key=lambda x: x.due_date, reverse=True)[:5]:
                        recent_activities.append({
                            'property': property.street_name,
                            'tenant': property.current_occupancy.tenant_name,
                            'amount': float(payment.amount),
                            'due_date': payment.due_date.strftime('%Y-%m-%d'),
                            'status': payment.status
                        })

            # Upcoming Lease Expirations (next 30 days)
            upcoming_expirations = []
            for property in properties:
                if property.current_occupancy:
                    days_until_expiry = (property.current_occupancy.lease_end_date - today).days
                    if 0 <= days_until_expiry <= 30:
                        upcoming_expirations.append({
                            'property': property.street_name,
                            'tenant': property.current_occupancy.tenant_name,
                            'expiry_date': property.current_occupancy.lease_end_date.strftime('%Y-%m-%d'),
                            'days_remaining': days_until_expiry
                        })

            # Overdue Payments
            overdue_payments = []
            for property in properties:
                if property.current_occupancy:
                    for payment in property.current_occupancy.payments:
                        if payment.status == 'due' and payment.due_date < today:
                            overdue_payments.append({
                                'property': property.street_name,
                                'tenant': property.current_occupancy.tenant_name,
                                'amount': float(payment.amount),
                                'due_date': payment.due_date.strftime('%Y-%m-%d'),
                                'days_overdue': (today - payment.due_date).days
                            })

            # Get all properties for notification settings
            properties_list = [{
                'property_id': p.property_id,
                'street_name': p.street_name,
                'city': p.city
            } for p in properties]

            return jsonify({
                'property_stats': property_stats,
                'financial_stats': financial_stats,
                'recent_activities': recent_activities,
                'upcoming_expirations': upcoming_expirations,
                'overdue_payments': overdue_payments,
                'properties': properties_list  # For notification settings dropdown
            }), 200

        except Exception as e:
            print(f"Dashboard Error: {str(e)}")  # For debugging
            return jsonify({'error': 'Failed to load dashboard data'}), 500

class PropertySummaryView(AuthenticatedMethodView):
    def get(self, property_id):
        """Get property summary"""
        property = Property.query.filter_by(
            property_id=property_id,
            user_id=session['user_id']
        ).first_or_404()
        
        return jsonify({
            'property': {
                'property_id': property.property_id,
                'property_type': property.property_type,
                'street_name': property.street_name,
                'city': property.city,
                'building_details': property.building_details,
                'size_sqft': property.size_sqft,
                'bedrooms': property.bedrooms,
                'occupancy_status': property.occupancy_status
            },
            'occupancy': property.current_occupancy.to_dict() if property.current_occupancy else None,
            'income_summary': property.get_income_summary(),
            'document_count': len(property.documents)
        }), 200

class PropertyOverviewView(AuthenticatedMethodView):
    def get(self):
        """Get properties overview statistics for the logged-in user"""
        if 'user_id' not in session:
            return jsonify({'error': 'User not logged in'}), 401

        user_id = session['user_id']
        
        # Total properties
        total_properties = Property.query.filter_by(user_id=user_id).count()

        # Occupied properties
        occupied_properties = Property.query.filter_by(user_id=user_id, occupancy_status='occupied').count()

        # Vacant properties
        vacant_properties = Property.query.filter_by(user_id=user_id, occupancy_status='vacant').count()
        
        # Occupancy rate
        Occupancy_rate = (occupied_properties / total_properties * 100) if total_properties > 0 else 0


        # Return the statistics as JSON
        return jsonify({
            'total_properties': total_properties,
            'occupied_properties': occupied_properties,
            'vacant_properties': vacant_properties,
            'Occupancy_rate': round(Occupancy_rate,1)
        })


class VacantPropertiesView(AuthenticatedMethodView):
    def get(self):
        """Get all vacant properties for the logged-in user"""
        if 'user_id' not in session:
            return jsonify({'error': 'User not logged in'}), 401

        try:
            vacant_properties = Property.query.filter_by(
                user_id=session['user_id'],
                occupancy_status='vacant'
            ).all()

            properties_data = [{
                'property_id': p.property_id,
                'property_type': p.property_type,
                'street_name': p.street_name,
                'city': p.city,
                'size_sqft': p.size_sqft,
                'bedrooms': p.bedrooms,
                'rent_per_month': p.rent_per_month,
                'units': p.units,
                'image': p.image or 'default.jpg'
            } for p in vacant_properties]

            return jsonify(properties_data), 200
        except Exception as e:
            return jsonify({'error': str(e)}), 500

class OccupantsOverviewView(AuthenticatedMethodView):
    def get(self):
        try:
            user_id = session.get('user_id')
            if not user_id:
                return jsonify({'error': 'Not authenticated'}), 401

            # Get all occupancies for user's properties with a single query
            occupancies = (db.session.query(Occupancy)
                         .join(Property, Occupancy.property_id == Property.property_id)
                         .filter(Property.user_id == user_id)
                         .all())

            today = datetime.now().date()
            
            # Initialize counters
            total_occupants = len(occupancies)
            active_occupants = 0
            pending_occupants = 0
            inactive_occupants = 0

            # Count occupants by status
            for occupancy in occupancies:
                if occupancy.lease_start_date > today:
                    pending_occupants += 1
                elif occupancy.lease_end_date < today:
                    inactive_occupants += 1
                else:
                    active_occupants += 1

            print(f"Debug - Total: {total_occupants}, Active: {active_occupants}, "
                  f"Pending: {pending_occupants}, Inactive: {inactive_occupants}")  # Debug print

            return jsonify({
                'total_occupants': total_occupants,
                'active_occupants': active_occupants,
                'pending_occupants': pending_occupants,
                'inactive_occupants': inactive_occupants
            }), 200

        except Exception as e:
            print("Error in occupants overview:", str(e))
            return jsonify({'error': str(e)}), 500
          
class OccupantPaymentsView(AuthenticatedMethodView):
    def get(self, occupancy_id):
        """Get all payments for a specific occupancy"""
        occupancy = Occupancy.query.filter_by(
            occupancy_id=occupancy_id
        ).first_or_404()

        payments = [
            {
                'payment_id': payment.payment_id,
                'amount': payment.amount,
                'due_date': payment.due_date.strftime('%Y-%m-%d'),
                'status': payment.status
            }
            for payment in occupancy.payments
        ]

        return jsonify(payments), 200

    def put(self, occupancy_id):
        """Update payment status for a specific occupancy"""
        data = request.json
        payment_id = data.get('payment_id')
        new_status = data.get('status')

        payment = Payment.query.filter_by(
            payment_id=payment_id,
            occupancy_id=occupancy_id
        ).first_or_404()

        if new_status not in ['due', 'paid']:
            return jsonify({'error': 'Invalid status'}), 400

        payment.status = new_status
        db.session.commit()

        return jsonify({'message': 'Payment status updated successfully'}), 200

def register_routes(app):
    """Register all routes with the Flask app"""
    @app.route('/api/signup')
    def signup_page3():
        return render_template('/signup.html')
    
    @app.route('/signup.html')
    def signup_page():
        return render_template('/signup.html')
    
    @app.route('/signup')
    def signup_page2():
        return render_template('/signup.html')

    @app.route('/login.html')
    def login_page():
        return render_template('/login.html')
    
    @app.route('/login')
    def login_page2():
        return render_template('/login.html')
    
    @app.route('/')
    def home():
        return render_template('/landing.html')
    
    @app.route('/landing.html')
    def home2():
        return render_template('/landing.html')

    # User routes

    app.add_url_rule('/login', view_func=LoginView.as_view('login'))
    app.add_url_rule('/api/signup', view_func=UserView.as_view('user'))
    
# ///////////////////////////////////////////////////////////
    @app.route('/dashboard.html')
    def dashboard():
            return render_template('dashboard.html')
    
    @app.route('/dashboard')
    def dashboard2():
            return render_template('dashboard.html')

    app.add_url_rule('/api/dashboard', view_func=DashboardView.as_view('dashboard_api'))

    
# ///////////////////////////////////////////////////////////

    # Property routes
    @app.route('/properties')
    def properties_page3():
        return render_template('properties.html')

    @app.route('/properties.html')
    def properties_page2():
        return render_template('properties.html')
    
    @app.route('/api/properties/<property_id>', methods=['GET'])
    def get_property_details(property_id):
        property = Property.query.filter_by(property_id=property_id, user_id=session['user_id']).first_or_404()
        return jsonify({
            'property_id': property.property_id,
            'property_type': property.property_type,
            'street_name': property.street_name,
            'city': property.city,
            'building_details': property.building_details,
            'size_sqft': property.size_sqft,
            'bedrooms': property.bedrooms,
            'units': property.units,
            'rent_per_month': property.rent_per_month,
            'occupancy_status': property.occupancy_status
        }), 200


    @app.route('/api/properties/<property_id>/full-details', methods=['GET'])
    def get_property_full_details(property_id):
        try:
            # Get property with related data
            property = Property.query.filter_by(
                property_id=property_id,
                user_id=session['user_id']
            ).first_or_404()

            # Calculate financial summary
            total_rent = 0
            total_paid = 0
            total_due = 0
            payment_percentage = 0

            if property.current_occupancy:
                total_rent = float(property.current_occupancy.total_rent)
                total_paid = sum(float(p.amount) for p in property.current_occupancy.payments if p.status == 'paid')
                total_due = sum(float(p.amount) for p in property.current_occupancy.payments if p.status == 'due')
                payment_percentage = (total_paid / total_rent * 100) if total_rent > 0 else 0

            # Prepare response data
            response_data = {
                'property_info': {
                    'property_id': property.property_id,
                    'property_type': property.property_type,
                    'street_name': property.street_name,
                    'city': property.city,
                    'building_details': property.building_details,
                    'size_sqft': property.size_sqft,
                    'bedrooms': property.bedrooms,
                    'units': property.units,
                    'rent_per_month': float(property.rent_per_month),
                    'occupancy_status': property.occupancy_status
                },
                'occupancy': None,
                'financial_summary': {
                    'total_rent': total_rent,
                    'total_paid': total_paid,
                    'total_due': total_due,
                    'payment_percentage': payment_percentage
                },
                'documents': {
                    'total_documents': len(property.documents),
                    'documents_list': [
                        {
                            'document_id': doc.document_id,
                            'title': doc.title,
                            'upload_date': doc.upload_date.strftime('%Y-%m-%d')
                        } for doc in property.documents
                    ]
                }
            }

            # Add occupancy information if property is occupied
            if property.current_occupancy:
                response_data['occupancy'] = {
                    'tenant_name': property.current_occupancy.tenant_name,
                    'tenant_phone': property.current_occupancy.tenant_phone,
                    'tenant_email': property.current_occupancy.tenant_email,
                    'lease_start_date': property.current_occupancy.lease_start_date.strftime('%Y-%m-%d'),
                    'lease_end_date': property.current_occupancy.lease_end_date.strftime('%Y-%m-%d'),
                    'payments_completed': sum(1 for p in property.current_occupancy.payments if p.status == 'paid')
                }

            return jsonify(response_data)

        except Exception as e:
            print(f"Error fetching property details: {str(e)}")
            return jsonify({'error': str(e)}), 500


    @app.route('/api/documents/<int:document_id>/download', methods=['GET'])
    def download_document(document_id):
        """Download a document by its ID."""
        try:
            # Fetch the document from the database
            document = Document.query.get_or_404(document_id)

            # Check if the file exists
            if not os.path.exists(document.file_path):
                return jsonify({'error': 'File not found'}), 404

            # Serve the file for download
            return send_file(document.file_path, as_attachment=True)

        except Exception as e:
            print(f"Error downloading document: {str(e)}")
            return jsonify({'error': 'Failed to download document'}), 500

    app.add_url_rule('/api/properties', view_func=PropertyView.as_view('properties'))
    app.add_url_rule(
        '/api/properties/<property_id>', 
        view_func=PropertyDetailView.as_view('property_detail'),
        methods=['GET', 'PUT', 'DELETE']  
    )
    app.add_url_rule('/api/properties/overview', view_func=PropertyOverviewView.as_view('properties_overview'))

# ///////////////////////////////////////////////////////////

    # Occupancy routes
    @app.route('/occupants')
    def occupants_page():
        return render_template('occupants.html')
    
    @app.route('/occupants.html')
    def occupants_page2():
        return render_template('occupants.html')

    app.add_url_rule(
        '/api/properties/vacant',
        view_func=VacantPropertiesView.as_view('vacant_properties')
    )
    app.add_url_rule(
        '/api/properties/<property_id>/occupancy',
        view_func=OccupancyView.as_view('occupancy'),
        methods=['POST', 'PUT', 'DELETE', 'VALIDATE_OCCUPANCY_DATA'] 
    )
    app.add_url_rule(
        '/api/occupants/overview',
        view_func=OccupantsOverviewView.as_view('occupants_overview')
    )
    app.add_url_rule(
        '/api/occupants/<int:occupancy_id>/payments',
        view_func=OccupantPaymentsView.as_view('occupant_payments'),
        methods=['GET', 'PUT'] 
    )

    @app.route('/api/occupants', methods=['GET'])
    def get_occupants():
        try:
            user_id = session.get('user_id')
            if not user_id:
                return jsonify({'error': 'Not authenticated'}), 401

            # Join with properties to get property information
            occupancies = (db.session.query(Occupancy, Property)
                        .join(Property, Occupancy.property_id == Property.property_id)
                        .filter(Property.user_id == user_id)
                        .all())

            today = datetime.now().date()
            
            occupants_list = []
            for occ in occupancies:
                # Determine status based on dates
                if occ.Occupancy.lease_start_date > today:
                    status = 'pending'
                elif occ.Occupancy.lease_end_date < today:
                    status = 'inactive'
                else:
                    status = 'active'

                # Get payment status summary
                total_payments = len(occ.Occupancy.payments)
                paid_payments = sum(1 for payment in occ.Occupancy.payments if payment.status == 'paid')
                
                occupants_list.append({
                    'occupancy_id': occ.Occupancy.occupancy_id,
                    'property_id': occ.Property.property_id,
                    'property_address': f"{occ.Property.street_name}, {occ.Property.city}",
                    'tenant_name': occ.Occupancy.tenant_name,
                    'tenant_phone': occ.Occupancy.tenant_phone,
                    'tenant_email': occ.Occupancy.tenant_email,
                    'lease_start_date': occ.Occupancy.lease_start_date.strftime('%Y-%m-%d'),
                    'lease_end_date': occ.Occupancy.lease_end_date.strftime('%Y-%m-%d'),
                    'total_rent': float(occ.Occupancy.total_rent),
                    'status': status,
                    'payment_summary': f"{paid_payments}/{total_payments} payments completed"
                })

            return jsonify(occupants_list)
        except Exception as e:
            print("Error in get_occupants:", str(e))
            return jsonify({'error': str(e)}), 500
    
    @app.route('/api/occupancies/<int:occupancy_id>', methods=['PUT'])
    def update_occupancy(occupancy_id):
        try:
            # Verify user is logged in
            if 'user_id' not in session:
                return jsonify({'error': 'Not authenticated'}), 401

            # Get the occupancy record
            occupancy = Occupancy.query.get_or_404(occupancy_id)
            
            # Verify the occupancy belongs to a property owned by the current user
            property = Property.query.filter_by(
                property_id=occupancy.property_id,
                user_id=session['user_id']
            ).first_or_404()

            data = request.json
            print("Received update data:", data)  # Debug log

            # Update occupancy details
            occupancy.tenant_name = data['tenant_name']
            occupancy.tenant_phone = data['tenant_phone']
            occupancy.tenant_email = data['tenant_email']
            occupancy.lease_start_date = datetime.strptime(data['lease_start_date'], '%Y-%m-%d')
            occupancy.lease_end_date = datetime.strptime(data['lease_end_date'], '%Y-%m-%d')
            occupancy.total_rent = float(data['total_rent'])

            # Handle payments update
            if 'payments' in data:
                # Delete existing payments
                Payment.query.filter_by(occupancy_id=occupancy_id).delete()
                
                # Create new payments with specified status
                for payment_data in data['payments']:
                    payment = Payment(
                        occupancy_id=occupancy_id,
                        amount=float(payment_data['amount']),
                        due_date=datetime.strptime(payment_data['date'], '%Y-%m-%d'),
                        status=payment_data['status']  
                    )
                    db.session.add(payment)
                    print(f"Adding payment: {payment_data}")  # Debug log
            else:
                # If no payments data provided, create new payment schedule
                payment_amount = occupancy.total_rent / data['number_of_payments']
                start_date = occupancy.lease_start_date
                
                for i in range(data['number_of_payments']):
                    due_date = start_date + timedelta(days=(30 * i))
                    payment = Payment(
                        occupancy_id=occupancy_id,
                        amount=payment_amount,
                        due_date=due_date,
                        status='due'
                    )
                    db.session.add(payment)

            try:
                db.session.commit()
                print("Successfully updated occupancy and payments")  # Debug log
                return jsonify({'message': 'Occupancy updated successfully'}), 200
            except Exception as e:
                db.session.rollback()
                print(f"Error during commit: {str(e)}")  # Debug log
                raise e

        except Exception as e:
            db.session.rollback()
            print("Error updating occupancy:", str(e))
            return jsonify({'error': str(e)}), 500
    
    
    @app.route('/api/occupancies/<int:occupancy_id>', methods=['GET'])
    def get_occupancy_details(occupancy_id):
        """Fetch details for a specific occupancy."""
        try:
            # Fetch the occupancy and related payments
            occupancy = Occupancy.query.filter_by(occupancy_id=occupancy_id).first_or_404()

            # Prepare data for the response
            occupancy_data = {
                'occupancy_id': occupancy.occupancy_id,
                'property_id': occupancy.property_id,
                'tenant_name': occupancy.tenant_name,
                'tenant_phone': occupancy.tenant_phone,
                'tenant_email': occupancy.tenant_email,
                'lease_start_date': occupancy.lease_start_date.strftime('%Y-%m-%d'),
                'lease_end_date': occupancy.lease_end_date.strftime('%Y-%m-%d'),
                'total_rent': occupancy.total_rent,
                'payments': [
                    {
                        'payment_id': payment.payment_id,
                        'amount': payment.amount,
                        'due_date': payment.due_date.strftime('%Y-%m-%d'),
                        'status': payment.status
                    }
                    for payment in occupancy.payments
                ]
            }

            return jsonify(occupancy_data), 200

        except Exception as e:
            print("Error fetching occupancy details:", str(e))
            return jsonify({'error': str(e)}), 500

    # @app.route('/api/properties/<property_id>/delete_occupancy', methods=['DELETE'])
    # def delete_property_occupancy(property_id):
    #     """Delete occupancy information for a specific property."""
    #     try:
    #         # Ensure the user is logged in
    #         if 'user_id' not in session:
    #             return jsonify({'error': 'User not logged in'}), 401

    #         # Fetch the property and validate its association with the logged-in user
    #         property = Property.query.filter_by(
    #             property_id=property_id,
    #             user_id=session['user_id']
    #         ).first_or_404()

    #         # Check if the property has active occupancy
    #         if not property.current_occupancy:
    #             return jsonify({'error': 'No occupancy information found for this property'}), 404

    #         occupancy = property.current_occupancy

    #         # Check for due payments
    #         due_payments = [
    #             {
    #                 'payment_id': payment.payment_id,
    #                 'amount': payment.amount,
    #                 'due_date': payment.due_date.strftime('%Y-%m-%d')
    #             }
    #             for payment in occupancy.payments if payment.status == 'due'
    #         ]

    #         # If there are due payments, warn the user before deletion
    #         if due_payments:
    #             return jsonify({
    #                 'warning': 'There are due payments associated with this occupancy.',
    #                 'due_payments': due_payments,
    #                 'requires_confirmation': True
    #             }), 200

    #         # Delete occupancy and associated payments
    #         db.session.delete(occupancy)
    #         property.occupancy_status = 'vacant'
    #         db.session.commit()

    #         return jsonify({'message': 'Occupancy information deleted successfully'}), 200

    #     except Exception as e:
    #         db.session.rollback()
    #         print("Error deleting occupancy:", str(e))
    #         return jsonify({'error': str(e)}), 500

    
    @app.route('/api/occupants/<int:occupancy_id>/check-delete', methods=['GET'])
    def check_delete_occupant(occupancy_id):
        """Check if occupant can be deleted and return due payments if any"""
        try:
            # Verify user is logged in
            if 'user_id' not in session:
                return jsonify({'error': 'Not authenticated'}), 401

            # Get the occupancy record
            occupancy = Occupancy.query.get_or_404(occupancy_id)
            
            # Verify the occupancy belongs to a property owned by the current user
            property = Property.query.filter_by(
                property_id=occupancy.property_id,
                user_id=session['user_id']
            ).first_or_404()

            # Check for due payments
            due_payments = Payment.query.filter_by(
                occupancy_id=occupancy_id,
                status='due'
            ).all()

            return jsonify({
                'occupancy_id': occupancy_id,
                'has_due_payments': len(due_payments) > 0,
                'due_payments': [{
                    'payment_id': payment.payment_id,
                    'amount': float(payment.amount),
                    'due_date': payment.due_date.strftime('%Y-%m-%d')
                } for payment in due_payments]
            })

        except Exception as e:
            print(f"Error checking occupant deletion: {str(e)}")
            return jsonify({'error': str(e)}), 500

    @app.route('/api/occupants/<int:occupancy_id>/delete', methods=['POST'])
    def delete_occupant(occupancy_id):
        """Delete an occupant and all related records"""
        try:
            # Verify user is logged in
            if 'user_id' not in session:
                return jsonify({'error': 'Not authenticated'}), 401

            # Get the occupancy record
            occupancy = Occupancy.query.get_or_404(occupancy_id)
            
            # Verify the occupancy belongs to a property owned by the current user
            property = Property.query.filter_by(
                property_id=occupancy.property_id,
                user_id=session['user_id']
            ).first_or_404()

            # Begin transaction
            db.session.begin_nested()

            try:
                # Delete all related payments first
                Payment.query.filter_by(occupancy_id=occupancy_id).delete()
                
                # Delete the occupancy
                db.session.delete(occupancy)
                
                # Update property status to vacant
                property.occupancy_status = 'vacant'
                
                # Commit the transaction
                db.session.commit()
                
                print(f"Successfully deleted occupant {occupancy_id} and all related records")
                return jsonify({'message': 'Occupant and all related records deleted successfully'})

            except Exception as e:
                db.session.rollback()
                raise e

        except Exception as e:
            print(f"Error deleting occupant: {str(e)}")
            return jsonify({'error': str(e)}), 500


# ///////////////////////////////////////////////////////////
    
    
    
    # Document routes
    @app.route('/documents')
    def documents_page():
        return render_template('documents.html')
    
    @app.route('/documents.html')
    def documents_page2():
        return render_template('documents.html')

    @app.route('/api/properties/<property_id>/documents', methods=['POST'])
    def upload_file(property_id):
        # Check if the request has a file
        if 'file' not in request.files:
            return jsonify({'error': 'No file part in the request'}), 400

        file = request.files['file']

        # Check if a file was selected
        if file.filename == '':
            return jsonify({'error': 'No file selected for uploading'}), 400

        # Validate and save the file
        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)  # Sanitize the filename
            file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(file_path)  # Save the file to the server

            # Save file metadata to the database
            new_document = Document(
                property_id=property_id,  # Get the property ID from the URL
                title=request.form.get('title', filename),  # Optional title, defaults to filename
                file_path=file_path
            )
            db.session.add(new_document)
            db.session.commit()

            return jsonify({'message': 'File uploaded successfully', 'file_path': file_path}), 200

        return jsonify({'error': 'Invalid file type'}), 400
    
    app.add_url_rule(
        '/api/properties/<property_id>/documents', 
        view_func=DocumentView.as_view('documents')
    )
    app.add_url_rule(
        '/api/documents/<document_id>',
        view_func=DocumentDetailView.as_view('document_detail')
    )
# ///////////////////////////////////////////////////////////
    
    # Income route
    @app.route('/income')
    def income_page():
        return render_template('income.html')
    
    @app.route('/income.html')
    def income_page2():
        return render_template('income.html')
    
    app.add_url_rule(
        '/api/properties/<property_id>/income',
        view_func=IncomeView.as_view('income')
    )
    
    # # Notification routes
    app.add_url_rule(
        '/api/properties/<property_id>/notifications',
        view_func=NotificationView.as_view('notifications'),
        methods=['GET', 'POST', 'DELETE']
    )
    app.add_url_rule(
        '/api/notifications/check',
        view_func=NotificationCheckView.as_view('check_notifications')
    )
    
    # # Summary routes
    # app.add_url_rule(
    #     '/api/properties/<property_id>/summary',
    #     view_func=PropertySummaryView.as_view('property_summary')
    # )
    # app.add_url_rule(
    #     '/api/dashboard',
    #     view_func=DashboardView.as_view('dashboard')
    # )

# Error handlers
@app.errorhandler(404)
def not_found_error(error):
    return jsonify({'error': 'Resource not found'}), 404

@app.errorhandler(500)
def internal_error(error):
    db.session.rollback()
    return jsonify({'error': 'Internal server error'}), 500

# Initialize the application
def init_app():
    if not os.path.exists(app.config['UPLOAD_FOLDER']):
        os.makedirs(app.config['UPLOAD_FOLDER'])
    
    with app.app_context():
        db.create_all()

if __name__ == '__main__':
    init_app()
    register_routes(app)
    app.run(debug=True)

