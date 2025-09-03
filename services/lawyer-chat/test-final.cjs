const bcrypt = require('bcryptjs');

async function testPasswords() {
    // Get the hashes we just updated in the database
    const demoHash = '$2a$12$FlggC69ExCZaqqaLv.d6gOfWIZJbRdLtfAfNz/dZw0JTohCblKliq';
    const adminHash = '$2a$12$B3GQNcs5JCDCBKA3zpxBG.r5ESM75LTtdAiqChGlFoUf3g6F8A9zq';
    
    console.log('Final verification of password hashes:');
    console.log('=====================================');
    
    const demoResult = await bcrypt.compare('demo123', demoHash);
    console.log('demo@reichmanjorgensen.com with "demo123":', demoResult ? '✅ VALID' : '❌ INVALID');
    
    const adminResult = await bcrypt.compare('admin123', adminHash);
    console.log('admin@reichmanjorgensen.com with "admin123":', adminResult ? '✅ VALID' : '❌ INVALID');
    
    console.log('\nThese credentials should now work in lawyer-chat!');
}

testPasswords();
