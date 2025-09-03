const bcrypt = require('bcryptjs');

async function generateHashes() {
    console.log('Generating correct hashes for passwords:');
    
    const demoHash = await bcrypt.hash('demo123', 12);
    console.log('demo123 hash:', demoHash);
    
    const adminHash = await bcrypt.hash('admin123', 12);
    console.log('admin123 hash:', adminHash);
    
    console.log('\nVerifying generated hashes:');
    console.log('demo123 verify:', await bcrypt.compare('demo123', demoHash));
    console.log('admin123 verify:', await bcrypt.compare('admin123', adminHash));
}

generateHashes();
