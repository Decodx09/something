"""
Simple script to view SQLite database contents
"""

import sqlite3
import os

def view_database(db_path="container_system.db"):
    """View all tables and their contents in the database"""
    
    if not os.path.exists(db_path):
        print(f"❌ Database file not found: {db_path}")
        return
    
    print(f"📊 Viewing database: {db_path}")
    print("=" * 50)
    
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Get list of tables
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = cursor.fetchall()
        
        if not tables:
            print("❌ No tables found in database")
            return
        
        print(f"📋 Found {len(tables)} tables:")
        for table in tables:
            print(f"  - {table[0]}")
        print()
        
        # View each table
        for table in tables:
            table_name = table[0]
            print(f"🗂️  Table: {table_name}")
            print("-" * 30)
            
            # Get table schema
            cursor.execute(f"PRAGMA table_info({table_name});")
            columns = cursor.fetchall()
            
            print("📐 Schema:")
            for col in columns:
                print(f"  {col[1]} ({col[2]})")
            print()
            
            # Get table data
            cursor.execute(f"SELECT * FROM {table_name};")
            rows = cursor.fetchall()
            
            if rows:
                # Get column names
                column_names = [col[1] for col in columns]
                
                print(f"📄 Data ({len(rows)} rows):")
                # Print headers
                header = " | ".join(column_names)
                print(header)
                print("-" * len(header))
                
                # Print data
                for row in rows:
                    row_str = " | ".join(str(cell) for cell in row)
                    print(row_str)
            else:
                print("📄 No data in table")
            
            print("\n" + "=" * 50 + "\n")
        
        conn.close()
        
    except Exception as e:
        print(f"❌ Error viewing database: {e}")

def view_specific_table(db_path="container_system.db", table_name=None):
    """View a specific table"""
    
    if not table_name:
        print("❌ Please specify a table name")
        return
    
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Check if table exists
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?;", (table_name,))
        if not cursor.fetchone():
            print(f"❌ Table '{table_name}' not found")
            return
        
        # Get table data
        cursor.execute(f"SELECT * FROM {table_name};")
        rows = cursor.fetchall()
        
        # Get column names
        cursor.execute(f"PRAGMA table_info({table_name});")
        columns = cursor.fetchall()
        column_names = [col[1] for col in columns]
        
        print(f"🗂️  Table: {table_name}")
        print(f"📄 Rows: {len(rows)}")
        print("-" * 40)
        
        if rows:
            # Print headers
            header = " | ".join(column_names)
            print(header)
            print("-" * len(header))
            
            # Print data
            for row in rows:
                row_str = " | ".join(str(cell) for cell in row)
                print(row_str)
        else:
            print("No data found")
        
        conn.close()
        
    except Exception as e:
        print(f"❌ Error viewing table: {e}")

if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1:
        # View specific table
        table_name = sys.argv[1]
        view_specific_table(table_name=table_name)
    else:
        # View all tables
        view_database() 