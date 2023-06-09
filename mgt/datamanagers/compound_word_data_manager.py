from mgt.datamanagers.compound_word.compound_word_mapper import CompoundWordMapper
from mgt.datamanagers.data_manager import DataManager, DataSet
from mgt.datamanagers.midi_wrapper import MidiWrapper, MidiToolkitWrapper
from mgt.datamanagers.remi.data_extractor import DataExtractor
from mgt.datamanagers.remi.dictionary_generator import DictionaryGenerator
from mgt.datamanagers.remi.to_midi_mapper import ToMidiMapper


defaults = {
    'transposition_steps': [0],
    'map_tracks_to_instruments': {},
    'instrument_mapping': {}
}


class CompoundWordDataManager(DataManager):
    """
    transposition_steps: Transposed copies of the data to include. For example [-1, 0, 1] has a copy that is transposed
                One semitone down, once the original track, and once transposed one semitone up.
    map_tracks_to_instruments: Whether to map certain track numbers to instruments. For example {0=0, 1=25} maps
                track 0 to a grand piano, and track 1 to an acoustic guitar.
    instrument_mapping: Maps instruments to different instruments. For example {1:0, 2:0, 3:0, 4:0, 5:0, 6:0, 7:0, 8:0}
                maps all piano-like instruments to a grand piano. Mapping to None removes the instrument entirely.
    """

    def __init__(
            self,
            transposition_steps=defaults['transposition_steps'],
            map_tracks_to_instruments=defaults['map_tracks_to_instruments'],
            instrument_mapping=defaults['instrument_mapping']
    ):
        self.transposition_steps = transposition_steps
        self.map_tracks_to_instruments = map_tracks_to_instruments
        self.instrument_mapping = instrument_mapping
        self.dictionary = DictionaryGenerator.create_dictionary()
        self.compound_word_mapper = CompoundWordMapper(self.dictionary)
        self.data_extractor = DataExtractor(
            dictionary=self.dictionary,
            map_tracks_to_instruments=self.map_tracks_to_instruments,
            use_chords=False,
            use_note_name=True,
            instrument_mapping=self.instrument_mapping
        )
        self.to_midi_mapper = ToMidiMapper(self.dictionary)

    def prepare_data(self, midi_paths) -> DataSet:
        training_data = []
        dic = {(i, j, k): index for index, (i, j, k) in enumerate((i, j, k) for i in range(12) for j in range(9) for k in range(64))}

        for path in midi_paths:
            for transposition_step in self.transposition_steps:
                try:
                    data = self.data_extractor.extract_words(path, transposition_step)

                    compound_words = self.compound_word_mapper.map_to_compound(data, self.dictionary)
                    compound_data = self.compound_word_mapper.map_compound_words_to_data(compound_words)
                    
                    cur = 0
                    for i in compound_data:
                      if i == [2,0,0,0,0,0,0,0]:
                        cur = cur + 1
                    measure = [[0]*6 for _ in range(16*(cur+1))] 

                    a = [[i[0], i[1], dic.get((i[4], i[5], i[6]))] for i in compound_data]
                    d = []
                    for i in a:
                      if i[0] == 2:
                        if i == [2,0,0]:
                          d.append(i)
                        b = i[1]
                      elif i[0] == 3:
                        c = i[2]
                        d.append([3,b,c])
                      else:
                        d.append(i)  
                    cur = 0
                    for i in d:
                        if i == [2, 0, 0]:
                            cur = cur + 1
                    p =[[] * 1 for i in range(cur*16+1)]
                    cur = -1
                    for i in d:
                        if i == [2, 0, 0]:
                            cur = cur + 1
                        if i[0] == 3:
                            p[i[1] + cur * 16].append([i[0],i[1],i[2]])

                    pp = []
                    cur = 0
                    for i in p:
                        if cur % 16==0:
                            pp.append([[2, 0, 0]])
                        if i:
                            pp.append(i)
                        cur = cur + 1
                    p  = []

                    for i in pp:
                        n =[0,0,0,0,0,0,0,0]
                        r = 2
                        for j in i:
                            n[0] = j[0]
                            n[1] = j[1]
                            n[r] = j[2]
                            if r >= 7:
                                break
                            r = r + 1
                        p.append(n)
                    if p[-1] == [2, 0, 0, 0, 0, 0, 0, 0]:
                        del p[-1]

                    cur = 0
                    for i in measure:
                        i[6] = cur % 16
                        cur = cur + 1 
                    cur = -1
                    for i in p:
                        if i == [2, 0, 0, 0, 0, 0, 0, 0]:
                            cur = cur + 1
                        else:
                            measure[i[1] + cur*16 -1] = [i[2],i[3],i[4],i[5],i[6],i[7],i[1]-1]

                    print(f'Extracted {len(measure)} compound words.')
                    print(measure)

                    training_data.append(measure)
                except Exception as e:
                    print(f"Exception: {e}")

        return DataSet(training_data, self.dictionary)

    def to_remi(self, data):
        remi = self.compound_word_mapper.map_to_remi(data)
        return list(map(lambda x: self.dictionary.data_to_word(x), remi))

    def to_midi(self, data) -> MidiWrapper:
        dic = {(i, j, k): index for index, (i, j, k) in enumerate((i, j, k) for i in range(12) for j in range(9) for k in range(64))}
        inverse_dic = {v: k for k, v in dic.items()}

        
        measure = data
        bar = -1
        a_reconstructed = []
        for beat in range(len(measure)):
            r=0
            if beat % 16 == 0:
                bar += 1
                a_reconstructed.append([2, 0, 0, 0, 0,0,0,0])
            for note_index, note_value in enumerate(measure[beat]):
                if note_index >= 6:
                    break
                if note_value != 0:
                    current_note = [3, beat - bar * 16 + 1, *inverse_dic[note_value]]
                    a_reconstructed.append(current_note)
        b = []
        con = 0
        for i in a_reconstructed:
            if i[0] == 2:
                b.append(i)
            if i[0] == 3:
                b.append([2, i[1], 0, 0, 0,0,0,0])
                b.append([3,i[1],0,0,i[2],i[3],i[4],31])
        
        remi = self.compound_word_mapper.map_to_remi(b)
        return MidiToolkitWrapper(self.to_midi_mapper.to_midi(remi))
